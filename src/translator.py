"""
translator.py — 翻译 agent

功能：
  1. translate_blocks(blocks, term_map, agent) -> None
     对 TranslatableBlock 列表就地填充 translation 字段。
     基于合并后的词典（term_map），通过系统提示词强制约束术语译名。
     每批约 10 段，自动分批调用 LLM。
     带指数退避重试（最多 MAX_RETRIES 次）。
     批次分段失败时自动降级为逐段翻译。

  2. translate_work(blocks, term_map, agent) -> None
     translate_blocks 的别名，供 main.py 统一调用。

  3. verify_terms(blocks, term_map) -> list[str]
     翻译完成后校验词典术语是否被 LLM 漏译（原文出现在译文中）。
     返回警告消息列表。

  4. 断点续传支持（_ato3_progress.json）：
     - save_progress(progress_path, blocks) 保存当前已翻译状态
     - load_progress(progress_path, blocks) 恢复已翻译内容，跳过已完成的块

用法（作为模块导入）：
    from html_parser import parse_ao3_html
    from dict_manager import load_dict, merge_dicts
    from translator import translate_work, verify_terms

    work = parse_ao3_html("test/example.html")
    general = load_dict("dicts/general.json")["terms"]
    translate_work(work.body, general)
    warnings = verify_terms(work.body, general)
    for w in warnings:
        print(w)
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# get_client 在模块顶层引用，使 patch("translator.get_client") 生效。
try:
    from .llm_config import get_client, get_agent_config as _get_agent_config
except ImportError:
    get_client = None  # type: ignore[assignment]
    _get_agent_config = None  # type: ignore[assignment]

try:
    from .llm_logger import log_call as _log_call
except ImportError:
    _log_call = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 耗时格式化与心跳计时器
# ---------------------------------------------------------------------------

def _fmt_elapsed(seconds: float) -> str:
    """将秒数格式化为可读耗时字符串。不足 60 秒显示 'Xs'，否则显示 'XmYs'。"""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


class _HeartbeatTimer:
    """在后台每隔 interval 秒打印一次「仍在进行」提示，直到调用 stop()。"""

    def __init__(self, label: str, interval: int = 60):
        self._label = label
        self._interval = interval
        self._stop_event = threading.Event()
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._thread.start()

    def stop(self) -> float:
        """停止心跳，返回从 start() 到 stop() 的总秒数。"""
        self._stop_event.set()
        self._thread.join()
        return time.monotonic() - self._start_time

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=self._interval):
            elapsed = time.monotonic() - self._start_time
            print(f"[等待] {self._label}仍在进行，已等待 {_fmt_elapsed(elapsed)}...", flush=True)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 每批最多发送的段落数
BATCH_SIZE = 10

# LLM 请求失败时的最大重试次数
MAX_RETRIES = 3

# 段落分隔符（在 LLM 请求和响应中使用）
PARAGRAPH_SEP = "---PARAGRAPH_SEP---"

# ---------------------------------------------------------------------------
# 提示词构建
# ---------------------------------------------------------------------------

# 源语言代码到中文名称的映射
_LANG_NAMES: dict[str, str] = {
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "fr": "法文",
    "de": "德文",
    "es": "西班牙文",
    "ru": "俄文",
    "zh": "中文",
}


def _get_lang_name(source_lang: str) -> str:
    """将语言代码转换为中文名称，未知代码直接返回原值。"""
    return _LANG_NAMES.get(source_lang.lower(), source_lang)


_SYSTEM_PROMPT_TEMPLATE = """\
你是一名专业的同人文翻译，将{source_lang}同人文翻译为简体中文。翻译要求：
1. 忠实原文，不增减内容，保留原文的语气和风格
2. 对话部分使用中文引号「」（除非原文整体风格更适合用""）
3. 人称代词根据上下文性别准确翻译
4. 涉及亲密或敏感内容时，直接准确翻译，不回避、不删改
5. 以下术语必须严格按照指定译名翻译，不得更改：

{term_list}

请直接输出译文，不要添加任何说明、注释或额外内容。
若输入包含多个段落（以 ---PARAGRAPH_SEP--- 分隔），输出时同样用 ---PARAGRAPH_SEP--- 分隔对应译文，段落数量必须与输入完全一致。\
"""

_SYSTEM_PROMPT_NO_TERMS = """\
你是一名专业的同人文翻译，将{source_lang}同人文翻译为简体中文。翻译要求：
1. 忠实原文，不增减内容，保留原文的语气和风格
2. 对话部分使用中文引号「」（除非原文整体风格更适合用""）
3. 人称代词根据上下文性别准确翻译
4. 涉及亲密或敏感内容时，直接准确翻译，不回避、不删改

请直接输出译文，不要添加任何说明、注释或额外内容。
若输入包含多个段落（以 ---PARAGRAPH_SEP--- 分隔），输出时同样用 ---PARAGRAPH_SEP--- 分隔对应译文，段落数量必须与输入完全一致。\
"""


def _build_system_prompt(term_map: dict[str, str], source_lang: str = "en") -> str:
    """根据词典和源语言构建系统提示词。词典为空时使用无术语表的简化版本。"""
    lang_name = _get_lang_name(source_lang)
    if not term_map:
        return _SYSTEM_PROMPT_NO_TERMS.format(source_lang=lang_name)

    term_lines = "\n".join(f"  {orig} -> {trans}" for orig, trans in term_map.items())
    return _SYSTEM_PROMPT_TEMPLATE.format(source_lang=lang_name, term_list=term_lines)


# ---------------------------------------------------------------------------
# 内部辅助：单次 LLM 调用
# ---------------------------------------------------------------------------

def _call_llm(
    text: str,
    system_prompt: str,
    client,
    agent_cfg: dict,
    label: str = "翻译",
    timeout: int = 120,
    batch_index: int = 1,
    total_batches: int = 1,
) -> str | None:
    """
    向 LLM 发送翻译请求，返回译文字符串。
    带指数退避重试（最多 MAX_RETRIES 次）和心跳计时器。
    所有重试均失败时返回 None。
    每次调用结果（成功或失败）均写入 llm_calls.jsonl 日志。
    """
    model_name = agent_cfg.get("model", "unknown")
    agent_name = agent_cfg.get("_agent_name", "translator")
    input_chars = len(text)

    for attempt in range(1, MAX_RETRIES + 1):
        hb = _HeartbeatTimer(label=label)
        hb.start()
        t0 = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model_name,
                temperature=agent_cfg["temperature"],
                timeout=timeout,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
            )
            elapsed = hb.stop()
            result_text = response.choices[0].message.content.strip()
            print(f"[完成] {label}完成（耗时 {_fmt_elapsed(elapsed)}）", flush=True)
            # 写入成功日志
            if _log_call is not None:
                log_line = _log_call(
                    phase="translate",
                    agent=agent_name,
                    model=model_name,
                    batch_index=batch_index,
                    total_batches=total_batches,
                    input_chars=input_chars,
                    output_chars=len(result_text),
                    elapsed_s=elapsed,
                    success=True,
                    error=None,
                )
                print(f"  [日志] llm_calls.jsonl 第 {log_line} 行", flush=True)
            return result_text
        except Exception as e:
            elapsed = hb.stop()
            err_str = str(e)
            # 超时检测：openai SDK 抛出 APITimeoutError 或消息包含 timeout
            is_timeout = (
                "timeout" in err_str.lower()
                or "timed out" in err_str.lower()
                or type(e).__name__ in ("APITimeoutError", "Timeout", "ConnectTimeout", "ReadTimeout")
            )
            # 写入失败日志
            if _log_call is not None:
                log_line = _log_call(
                    phase="translate",
                    agent=agent_name,
                    model=model_name,
                    batch_index=batch_index,
                    total_batches=total_batches,
                    input_chars=input_chars,
                    output_chars=0,
                    elapsed_s=elapsed,
                    success=False,
                    error=err_str[:500],
                )
            else:
                log_line = None

            if attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2, 4 秒
                if is_timeout:
                    print(
                        f"  [翻译] 第 {attempt} 次请求超时（超过 {timeout}s）"
                        f"，{wait} 秒后重试..."
                    )
                else:
                    print(f"  [翻译] 第 {attempt} 次请求失败：{e}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                if is_timeout:
                    print(
                        f"  [翻译] 请求超时（已重试 {MAX_RETRIES} 次，每次超过 {timeout}s）。\n"
                        f"  提示：可在 config.json agents.translator.timeout 中调大超时秒数，\n"
                        f"        或检查网络连通性后重新运行（进度已自动保存，将从断点继续）。"
                    )
                else:
                    print(f"  [翻译] 请求失败（已重试 {MAX_RETRIES} 次）：{e}")
                if log_line is not None:
                    print(f"  [日志] 详情见 llm_calls.jsonl 第 {log_line} 行")
                return None
    return None


# ---------------------------------------------------------------------------
# 内部辅助：分批翻译
# ---------------------------------------------------------------------------

def _translate_batch(
    batch: list,
    system_prompt: str,
    client,
    agent_cfg: dict,
    batch_index: int,
    total_batches: int,
    timeout: int = 120,
) -> None:
    """
    翻译一批 TranslatableBlock，就地填充 translation 字段。
    若 LLM 返回的段落数与输入不匹配，自动降级为逐段翻译。
    """
    if not batch:
        return

    # 单段直接翻译，不使用分隔符（减少 LLM 误解风险）
    if len(batch) == 1:
        label = f"第 {batch_index} 段翻译"
        print(f"  批次 {batch_index}/{total_batches}（1 段）...")
        result = _call_llm(
            batch[0].text, system_prompt, client, agent_cfg,
            label=label, timeout=timeout,
            batch_index=batch_index, total_batches=total_batches,
        )
        if result is None:
            print("  失败，保留空译文")
        else:
            batch[0].translation = result
        return

    # 多段合并翻译
    combined = f"\n\n{PARAGRAPH_SEP}\n\n".join(b.text for b in batch)
    label = f"第 {batch_index} 批翻译"
    print(
        f"  批次 {batch_index}/{total_batches}（{len(batch)} 段，{len(combined)} 字符）..."
    )
    raw_result = _call_llm(
        combined, system_prompt, client, agent_cfg,
        label=label, timeout=timeout,
        batch_index=batch_index, total_batches=total_batches,
    )

    if raw_result is None:
        print("  失败，批次降级为逐段翻译...")
        _fallback_translate_one_by_one(batch, system_prompt, client, agent_cfg, timeout=timeout,
                                       batch_offset=batch_index, total_batches=total_batches)
        return

    # 按分隔符拆分译文
    parts = [p.strip() for p in raw_result.split(PARAGRAPH_SEP)]

    if len(parts) != len(batch):
        print(
            f"  段落数不匹配（期望 {len(batch)}，实际 {len(parts)}），降级为逐段翻译..."
        )
        _fallback_translate_one_by_one(batch, system_prompt, client, agent_cfg, timeout=timeout,
                                       batch_offset=batch_index, total_batches=total_batches)
        return

    for block, translated_text in zip(batch, parts):
        block.translation = translated_text


def _fallback_translate_one_by_one(
    batch: list,
    system_prompt: str,
    client,
    agent_cfg: dict,
    timeout: int = 120,
    batch_offset: int = 1,
    total_batches: int = 1,
) -> None:
    """降级方案：对批次中每段逐一单独翻译。"""
    for i, block in enumerate(batch, 1):
        if block.translation:
            # 已有译文（断点续传），跳过
            continue
        label = f"降级翻译第 {i}/{len(batch)} 段"
        print(f"    {label}...")
        result = _call_llm(
            block.text, system_prompt, client, agent_cfg,
            label=label, timeout=timeout,
            batch_index=batch_offset, total_batches=total_batches,
        )
        if result is not None:
            block.translation = result
        else:
            print("    失败，保留空译文")


# ---------------------------------------------------------------------------
# 断点续传
# ---------------------------------------------------------------------------

def save_progress(progress_path: str | Path, blocks: list) -> None:
    """
    将当前已翻译内容保存到 JSON 文件（断点续传用）。
    保存格式：{block_id: translation}，只保存已翻译（非空）的条目。
    """
    progress_path = Path(progress_path)
    data: dict[str, str] = {}
    for block in blocks:
        if block.translation:
            data[block.block_id] = block.translation

    # 原子写入：先写临时文件再替换
    tmp_path = progress_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_path.replace(progress_path)
    except Exception as e:
        print(f"  [断点续传] 保存进度失败：{e}")


def load_progress(progress_path: str | Path, blocks: list) -> int:
    """
    从 JSON 文件恢复已翻译内容，回填到 blocks 的 translation 字段。
    返回已恢复的条目数。
    若文件不存在或解析失败，返回 0（不抛异常）。
    """
    progress_path = Path(progress_path)
    if not progress_path.exists():
        return 0

    try:
        data: dict[str, str] = json.loads(
            progress_path.read_text(encoding="utf-8")
        )
    except Exception as e:
        print(f"  [断点续传] 读取进度文件失败：{e}，将从头开始翻译。")
        return 0

    id_to_block = {b.block_id: b for b in blocks}
    restored = 0
    for block_id, translation in data.items():
        if block_id in id_to_block and translation:
            id_to_block[block_id].translation = translation
            restored += 1

    return restored


# ---------------------------------------------------------------------------
# 公开 API：翻译
# ---------------------------------------------------------------------------

def translate_blocks(
    blocks: list,
    term_map: dict[str, str] | None = None,
    agent: str = "translator",
    progress_path: str | Path | None = None,
    source_lang: str = "en",
    profile: dict | None = None,
) -> None:
    """
    对 TranslatableBlock 列表进行翻译，就地填充每个 block 的 translation 字段。

    参数
    ----
    blocks        : TranslatableBlock 列表（来自 html_parser）
    term_map      : 合并后的术语映射 {原文: 译文}，注入系统提示词
    agent         : 使用的 agent 名称（对应 config.json 中的配置）
    progress_path : 断点续传文件路径（_ato3_progress.json），None 则不使用断点续传
    source_lang   : 源语言代码（如 "en"、"ja"），用于提示词中描述源文语言
    profile       : 由 get_profile_config() 返回的方案配置字典（可选）。
                    不为 None 时优先从方案中取 agent 配置，否则沿用旧版逻辑。

    说明
    ----
    - 每批最多 BATCH_SIZE（10）段，超出则自动分批
    - 每批翻译完成后立即保存进度（若 progress_path 不为 None）
    - 分隔符不匹配时自动降级为逐段翻译
    - 词典通过系统提示词注入，LLM 漏译校验由 verify_terms() 负责
    """
    if not blocks:
        return

    term_map = term_map or {}

    # 获取 LLM 客户端
    if get_client is None:
        raise ImportError(
            "llm_config 模块未找到，请确认项目根目录下存在 llm_config.py。"
        )
    client, agent_cfg = get_client(agent, profile_config=profile)
    # 注入 agent 名称，供 _call_llm 写日志时使用
    agent_cfg = dict(agent_cfg)
    agent_cfg["_agent_name"] = agent

    # 构建系统提示词（优先使用 config.json 中的自定义提示词）
    custom_prompt: str | None = None
    try:
        if _get_agent_config is not None:
            _cfg = _get_agent_config(agent)
            custom_prompt = _cfg.get("system_prompt") or None
    except Exception:
        pass
    if custom_prompt:
        # 自定义提示词：追加术语表（若有），不替换整个提示词
        if term_map:
            term_lines = "\n".join(f"  {orig} -> {trans}" for orig, trans in term_map.items())
            system_prompt = custom_prompt + f"\n\n以下术语必须严格按照指定译名翻译，不得更改：\n{term_lines}"
        else:
            system_prompt = custom_prompt
    else:
        system_prompt = _build_system_prompt(term_map, source_lang=source_lang)

    # 断点续传：恢复已翻译内容
    if progress_path is not None:
        restored = load_progress(progress_path, blocks)
        if restored > 0:
            print(f"[翻译] 断点续传：已恢复 {restored} 个已翻译段落")

    # 过滤出待翻译的块（跳过已有译文的块）
    pending = [b for b in blocks if not b.translation and b.text.strip()]
    already_done = len(blocks) - len(pending)

    total_blocks = len(blocks)
    if already_done > 0:
        print(f"[翻译] 共 {total_blocks} 段，其中 {already_done} 段已完成，待翻译 {len(pending)} 段")
    else:
        print(f"[翻译] 共 {total_blocks} 段，分批翻译中（每批最多 {BATCH_SIZE} 段）...")

    if not pending:
        print("[翻译] 所有段落均已翻译，跳过。")
        return

    # 从 agent 配置读取超时时间（秒），默认 120
    llm_timeout = int(agent_cfg.get("timeout", 120))

    # 分批翻译
    total_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        batch_index = i // BATCH_SIZE + 1
        _translate_batch(batch, system_prompt, client, agent_cfg, batch_index, total_batches, timeout=llm_timeout)

        # 每批完成后保存进度
        if progress_path is not None:
            save_progress(progress_path, blocks)

    print(f"[翻译] 完成，共翻译 {len(pending)} 段。")


def translate_work(
    blocks: list,
    term_map: dict[str, str] | None = None,
    agent: str = "translator",
    progress_path: str | Path | None = None,
    source_lang: str = "en",
    profile: dict | None = None,
) -> None:
    """
    translate_blocks 的别名，供 main.py 调用（接口与计划书一致）。
    """
    translate_blocks(
        blocks, term_map=term_map, agent=agent,
        progress_path=progress_path, source_lang=source_lang, profile=profile,
    )


# ---------------------------------------------------------------------------
# 公开 API：词典术语校验
# ---------------------------------------------------------------------------

def verify_terms(
    blocks: list,
    term_map: dict[str, str],
) -> list[str]:
    """
    翻译后校验：扫描所有译文，若词典中的原文（英文）仍出现在译文中，
    说明 LLM 漏译了该术语，生成警告消息。

    参数
    ----
    blocks   : 已翻译的 TranslatableBlock 列表
    term_map : 术语映射 {原文: 译文}

    返回
    ----
    list[str]：警告消息列表（空列表表示无漏译）

    说明
    ----
    - 匹配为大小写不敏感的全词匹配（使用单词边界，避免误报缩写）
    - 只检查有译文的块；无译文的块不产生警告
    """
    import re

    if not term_map or not blocks:
        return []

    warnings: list[str] = []

    for block in blocks:
        if not block.translation:
            continue

        translation_lower = block.translation.lower()
        for orig, trans in term_map.items():
            # 跳过过短的词（1-2 个字符，误报风险高）
            if len(orig) <= 2:
                continue
            # 大小写不敏感的全词匹配
            # 若词汇全部由非 ASCII 字符组成（日/韩/法文等），\b 无法识别其边界，
            # 直接用 re.escape 不加边界；含 ASCII 字符的词汇保留 \b 避免误报。
            orig_lower = orig.lower()
            if all(ord(c) > 127 for c in orig_lower.replace(" ", "")):
                pattern = re.escape(orig_lower)
            else:
                pattern = r"\b" + re.escape(orig_lower) + r"\b"
            if re.search(pattern, translation_lower):
                warnings.append(
                    f"[漏译警告] 块 {block.block_id!r}：词典术语 {orig!r} 未被翻译为 {trans!r}，"
                    f"仍以原文出现在译文中。"
                )

    return warnings


# ---------------------------------------------------------------------------
# CLI 快速测试入口（python translator.py <html_path>）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("translator.py — 直接运行模式（快速测试）")
    print()

    if len(sys.argv) < 2:
        print("用法：python translator.py <AO3_HTML文件路径> [agent名称]")
        print("示例：python translator.py test/Tease_Test_Taste.html translator")
        sys.exit(1)

    html_path = sys.argv[1]
    agent_name = sys.argv[2] if len(sys.argv) > 2 else "translator"

    try:
        from html_parser import parse_ao3_html
        from dict_manager import load_dict
    except ImportError as e:
        print(f"[错误] 无法导入依赖模块：{e}")
        sys.exit(1)

    print(f"正在解析：{html_path}")
    try:
        work = parse_ao3_html(html_path)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"解析完成：正文 {len(work.body)} 段，标签 {len(work.tags)} 条")

    # 加载通用词典
    general_path = Path(html_path).parent.parent / "dicts" / "general.json"
    term_map: dict[str, str] = {}
    if general_path.exists():
        try:
            term_data = load_dict(str(general_path))
            term_map = term_data.get("terms", {})
            print(f"已加载词典：{len(term_map)} 条术语")
        except Exception as e:
            print(f"[警告] 加载词典失败：{e}，将不使用术语约束")

    # 只翻译前 2 段（演示模式）
    demo_blocks = work.body[:2]
    print(f"\n（演示模式：仅翻译前 {len(demo_blocks)} 段正文）")

    try:
        translate_work(demo_blocks, term_map=term_map, agent=agent_name)
    except (ImportError, EnvironmentError, KeyError) as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print()
    for i, block in enumerate(demo_blocks, 1):
        print(f"--- 第 {i} 段 ---")
        print(f"原文：{block.text[:100]}{'...' if len(block.text) > 100 else ''}")
        print(f"译文：{block.translation[:100]}{'...' if len(block.translation) > 100 else ''}")
        print()

    warnings = verify_terms(demo_blocks, term_map)
    if warnings:
        print("词典术语校验警告：")
        for w in warnings:
            print(f"  {w}")
    else:
        print("词典术语校验：无漏译。")
