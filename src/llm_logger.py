"""
llm_logger.py — LLM 调用日志记录模块（JSONL 格式）

功能：
  每次 LLM API 调用完成（或失败）后，将调用信息追加写入
  logs/llm_calls.jsonl 文件，每行一条 JSON 记录。

记录字段：
  timestamp     str    ISO 8601 时间戳（UTC）
  phase         str    调用阶段（term_extract / translate / polish）
  agent         str    agent 名称（如 "translator"）
  model         str    实际使用的模型名
  batch_index   int    批次编号（1-based），单段为 1
  total_batches int    本阶段总批次数
  input_chars   int    用户消息字符数
  output_chars  int    LLM 响应字符数（失败时为 0）
  elapsed_s     float  耗时（秒）
  success       bool   是否成功
  error         str    失败原因（成功时为 null）
  log_line      int    本条日志在文件中的行号（1-based，便于定位）

用法（由 translator / polisher / term_extractor 内部调用）：
    from .llm_logger import log_call

    log_call(
        phase="translate",
        agent="translator",
        model="deepseek-v3",
        batch_index=1,
        total_batches=5,
        input_chars=1200,
        output_chars=980,
        elapsed_s=3.14,
        success=True,
        error=None,
    )
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 日志文件路径（logs/ 子目录，与任务状态文件同级）
_LOG_PATH: Path = Path(__file__).parent.parent / "logs" / "llm_calls.jsonl"

# 写入锁，防止多线程竞争（心跳线程与主线程同时写入时）
_write_lock = threading.Lock()


def get_log_path() -> Path:
    """返回当前日志文件的绝对路径。"""
    return _LOG_PATH


def log_call(
    phase: str,
    agent: str,
    model: str,
    batch_index: int,
    total_batches: int,
    input_chars: int,
    output_chars: int,
    elapsed_s: float,
    success: bool,
    error: Optional[str] = None,
) -> int:
    """
    将一次 LLM 调用记录追加到 llm_calls.jsonl。

    参数
    ----
    phase         : 调用阶段（"term_extract" / "translate" / "polish"）
    agent         : agent 配置名称（如 "translator"）
    model         : 实际使用的模型名
    batch_index   : 批次编号（1-based）
    total_batches : 本阶段总批次数
    input_chars   : 用户消息字符数（输入长度估算）
    output_chars  : LLM 响应字符数（失败时传 0）
    elapsed_s     : 本次调用耗时（秒）
    success       : 是否成功
    error         : 失败原因（成功时传 None）

    返回
    ----
    int：本条日志在文件中的行号（1-based），可用于错误提示中定位
    """
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with _write_lock:
        # 计算行号（写入前统计已有行数）
        log_line = 1
        if _LOG_PATH.exists():
            try:
                content = _LOG_PATH.read_bytes()
                # 行数 = 换行符数量 + 1（若末尾有内容）
                log_line = content.count(b"\n") + 1
            except OSError:
                log_line = 1

        record = {
            "timestamp": timestamp,
            "phase": phase,
            "agent": agent,
            "model": model,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "input_chars": input_chars,
            "output_chars": output_chars,
            "elapsed_s": round(elapsed_s, 3),
            "success": success,
            "error": error,
            "log_line": log_line,
        }

        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            # 日志写入失败不应阻断主流程，仅打印警告
            print(f"[llm_logger] 日志写入失败：{e}", flush=True)

    return log_line


def get_recent_entries(n: int = 20) -> list[dict]:
    """
    读取最近 n 条日志记录（用于调试或错误报告）。
    若文件不存在或读取失败，返回空列表。
    """
    if not _LOG_PATH.exists():
        return []
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        recent_lines = lines[-n:] if len(lines) > n else lines
        entries = []
        for line in recent_lines:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries
    except OSError:
        return []
