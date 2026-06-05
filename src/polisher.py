"""
polisher.py — 润色 agent

功能：
  1. polish_blocks(blocks, agent, skip_polish) -> None
     对已翻译的 TranslatableBlock 列表进行润色，就地覆盖 translation 字段。
     润色要点：对话引号规范化、全角标点、破折号统一为——。
     每批约 10 段，与翻译模块保持相同的分批策略。
     带指数退避重试（最多 MAX_RETRIES 次）。
     批次分段失败时自动降级为逐段润色。

  2. polish_work(blocks, agent, skip_polish) -> None
     polish_blocks 的别名，供 main.py 统一调用。
     skip_polish=True 时立即返回，不调用 LLM。

用法（作为模块导入）：
    from polisher import polish_work

    # 翻译完成后润色正文（正常模式）
    polish_work(work.body, agent="polisher")

    # 跳过润色（--skip-polish 参数）
    polish_work(work.body, skip_polish=True)
"""

from __future__ import annotations

import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# get_client / get_agent_config 在模块顶层引用，使 patch("polisher.get_client") 生效。
try:
    from .llm_config import get_client, get_agent_config
except ImportError:
    get_client = None  # type: ignore[assignment]
    get_agent_config = None  # type: ignore[assignment]

try:
    from .llm_logger import log_call as _log_call
except ImportError:
    _log_call = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 耗时格式化与心跳计时器（与 translator.py 保持一致）
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

# 每批最多发送的段落数（与翻译模块保持一致）
BATCH_SIZE = 10

# LLM 请求失败时的最大重试次数
MAX_RETRIES = 3

# 段落分隔符（与翻译模块保持一致）
PARAGRAPH_SEP = "---PARAGRAPH_SEP---"

# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

# 源语言代码到中文名称的映射（与 translator.py 保持一致）
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
你是一名资深的简体中文同人文编辑，以下文本由{source_lang}翻译而来，请对其进行润色：
1. 对话部分统一使用「」引号（或根据文章整体风格决定），确保对话标点规范
2. 修正不通顺的句子，但不改变原文意思
3. 中文标点（逗号、句号、问号、感叹号）使用全角形式
4. 破折号使用——（两个全角破折号）
5. 不删减内容，不改变叙事风格

请直接输出润色后的文本，不要添加任何说明、注释或额外内容。
若输入包含多个段落（以 ---PARAGRAPH_SEP--- 分隔），输出时同样用 ---PARAGRAPH_SEP--- 分隔对应段落，段落数量必须与输入完全一致。\
"""

# ---------------------------------------------------------------------------
# 内部辅助：单次 LLM 调用
# ---------------------------------------------------------------------------


def _call_llm(
    text: str,
    client,
    agent_cfg: dict,
    system_prompt: str | None = None,
    label: str = "润色",
    timeout: int = 120,
    batch_index: int = 1,
    total_batches: int = 1,
) -> str | None:
    """
    向 LLM 发送润色请求，返回润色后的文本字符串。
    带指数退避重试（最多 MAX_RETRIES 次）和心跳计时器。
    所有重试均失败时返回 None。
    system_prompt 为 None 时使用默认英文提示词。
    每次调用结果均写入 llm_calls.jsonl 日志。
    """
    if system_prompt is None:
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(source_lang=_get_lang_name("en"))

    model_name = agent_cfg.get("model", "unknown")
    agent_name = agent_cfg.get("_agent_name", "polisher")
    input_chars = len(text)

    for attempt in range(1, MAX_RETRIES + 1):
        hb = _HeartbeatTimer(label=label)
        hb.start()
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
                    phase="polish",
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
            is_timeout = (
                "timeout" in err_str.lower()
                or "timed out" in err_str.lower()
                or type(e).__name__ in ("APITimeoutError", "Timeout", "ConnectTimeout", "ReadTimeout")
            )
            # 写入失败日志
            if _log_call is not None:
                log_line = _log_call(
                    phase="polish",
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
                        f"  [润色] 第 {attempt} 次请求超时（超过 {timeout}s）"
                        f"，{wait} 秒后重试..."
                    )
                else:
                    print(f"  [润色] 第 {attempt} 次请求失败：{e}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                if is_timeout:
                    print(
                        f"  [润色] 请求超时（已重试 {MAX_RETRIES} 次，每次超过 {timeout}s）。\n"
                        f"  提示：可在 config.json agents.polisher.timeout 中调大超时秒数，\n"
                        f"        或检查网络连通性后重新运行。"
                    )
                else:
                    print(f"  [润色] 请求失败（已重试 {MAX_RETRIES} 次）：{e}")
                if log_line is not None:
                    print(f"  [日志] 详情见 llm_calls.jsonl 第 {log_line} 行")
                return None
    return None


# ---------------------------------------------------------------------------
# 内部辅助：分批润色
# ---------------------------------------------------------------------------


def _polish_batch(
    batch: list,
    client,
    agent_cfg: dict,
    batch_index: int,
    total_batches: int,
    system_prompt: str | None = None,
    timeout: int = 120,
) -> None:
    """
    润色一批 TranslatableBlock，就地覆盖 translation 字段。
    若 LLM 返回的段落数与输入不匹配，自动降级为逐段润色。
    只处理有译文的块；无译文的块原样跳过。
    """
    if not batch:
        return

    # 过滤出有译文的块（无译文的块无需润色）
    valid = [b for b in batch if b.translation and b.translation.strip()]
    if not valid:
        return

    # 单段直接润色，不使用分隔符
    if len(valid) == 1:
        label = f"第 {batch_index} 段润色"
        print(f"  批次 {batch_index}/{total_batches}（1 段）...")
        result = _call_llm(
            valid[0].translation, client, agent_cfg,
            system_prompt=system_prompt, label=label, timeout=timeout,
            batch_index=batch_index, total_batches=total_batches,
        )
        if result is None:
            print("  失败，保留原译文")
        else:
            valid[0].translation = result
        return

    # 多段合并润色
    combined = f"\n\n{PARAGRAPH_SEP}\n\n".join(b.translation for b in valid)
    label = f"第 {batch_index} 批润色"
    print(
        f"  批次 {batch_index}/{total_batches}（{len(valid)} 段，{len(combined)} 字符）..."
    )
    raw_result = _call_llm(
        combined, client, agent_cfg,
        system_prompt=system_prompt, label=label, timeout=timeout,
        batch_index=batch_index, total_batches=total_batches,
    )

    if raw_result is None:
        print("  失败，批次降级为逐段润色...")
        _fallback_polish_one_by_one(
            valid, client, agent_cfg, system_prompt=system_prompt, timeout=timeout,
            batch_offset=batch_index, total_batches=total_batches,
        )
        return

    # 按分隔符拆分润色结果
    parts = [p.strip() for p in raw_result.split(PARAGRAPH_SEP)]

    if len(parts) != len(valid):
        print(
            f"  段落数不匹配（期望 {len(valid)}，实际 {len(parts)}），降级为逐段润色..."
        )
        _fallback_polish_one_by_one(
            valid, client, agent_cfg, system_prompt=system_prompt, timeout=timeout,
            batch_offset=batch_index, total_batches=total_batches,
        )
        return

    for block, polished_text in zip(valid, parts):
        block.translation = polished_text


def _fallback_polish_one_by_one(
    batch: list,
    client,
    agent_cfg: dict,
    system_prompt: str | None = None,
    timeout: int = 120,
    batch_offset: int = 1,
    total_batches: int = 1,
) -> None:
    """降级方案：对批次中每段逐一单独润色。"""
    for i, block in enumerate(batch, 1):
        if not block.translation or not block.translation.strip():
            continue
        label = f"降级润色第 {i}/{len(batch)} 段"
        print(f"    {label}...")
        result = _call_llm(
            block.translation, client, agent_cfg,
            system_prompt=system_prompt, label=label, timeout=timeout,
            batch_index=batch_offset, total_batches=total_batches,
        )
        if result is not None:
            block.translation = result
        else:
            print("    失败，保留原译文")


# ---------------------------------------------------------------------------
# 公开 API：润色
# ---------------------------------------------------------------------------


def _polish_full(
    blocks: list,
    client,
    agent_cfg: dict,
    system_prompt: str,
    token_limit: int,
    timeout: int = 120,
) -> None:
    """
    全文模式润色：将全部有译文段落拼为一个请求。
    若估算 token 数超过 token_limit，自动降级为段落模式。
    """
    translatable = [b for b in blocks if b.translation and b.translation.strip()]
    if not translatable:
        return

    combined = f"\n\n{PARAGRAPH_SEP}\n\n".join(b.translation for b in translatable)
    estimated_tokens = len(combined) // 3  # 粗估

    if estimated_tokens > token_limit:
        print(
            f"[润色] 全文模式：估算 token 数 ~{estimated_tokens} 超过限制 {token_limit}，"
            f"自动降级为段落模式。"
        )
        _polish_paragraph_mode(blocks, client, agent_cfg, system_prompt, timeout=timeout)
        return

    print(
        f"[润色] 全文模式：{len(translatable)} 段，约 {estimated_tokens} tokens，发送单次请求..."
    )
    _polish_batch(translatable, client, agent_cfg, 1, 1, system_prompt=system_prompt, timeout=timeout)


def _polish_chapter_mode(
    chapters: list[list],
    client,
    agent_cfg: dict,
    system_prompt: str,
    token_limit: int,
    timeout: int = 120,
) -> None:
    """
    章节模式润色：每章作为一个请求。
    若单章估算超过 token_limit，该章降级为段落模式。
    """
    total_ch = len(chapters)
    for ch_idx, ch_blocks in enumerate(chapters, 1):
        translatable = [b for b in ch_blocks if b.translation and b.translation.strip()]
        if not translatable:
            continue
        combined = f"\n\n{PARAGRAPH_SEP}\n\n".join(b.translation for b in translatable)
        estimated = len(combined) // 3
        if estimated > token_limit:
            print(
                f"[润色] 章节模式：第 {ch_idx}/{total_ch} 章（~{estimated} tokens 超限），降级为段落模式..."
            )
            _polish_paragraph_mode(ch_blocks, client, agent_cfg, system_prompt, timeout=timeout)
        else:
            print(
                f"[润色] 章节模式：第 {ch_idx}/{total_ch} 章（{len(translatable)} 段，~{estimated} tokens）..."
            )
            _polish_batch(translatable, client, agent_cfg, ch_idx, total_ch, system_prompt=system_prompt, timeout=timeout)


def _polish_paragraph_mode(
    blocks: list,
    client,
    agent_cfg: dict,
    system_prompt: str,
    timeout: int = 120,
) -> None:
    """段落模式润色（原有逻辑，每批最多 BATCH_SIZE 段）。"""
    translatable = [b for b in blocks if b.translation and b.translation.strip()]
    if not translatable:
        return
    total_batches = (len(translatable) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(translatable), BATCH_SIZE):
        batch = translatable[i : i + BATCH_SIZE]
        batch_index = i // BATCH_SIZE + 1
        _polish_batch(batch, client, agent_cfg, batch_index, total_batches, system_prompt=system_prompt, timeout=timeout)


def polish_blocks(
    blocks: list,
    agent: str = "polisher",
    skip_polish: bool = False,
    source_lang: str = "en",
    chapters: list[list] | None = None,
    profile: dict | None = None,
) -> None:
    """
    对 TranslatableBlock 列表进行润色，就地覆盖每个 block 的 translation 字段。

    参数
    ----
    blocks       : TranslatableBlock 列表（来自 html_parser，已完成翻译）
    agent        : 使用的 agent 名称（对应 config.json 中的配置）
    skip_polish  : 若为 True，立即返回，不调用 LLM（对应 --skip-polish 参数）
    source_lang  : 源语言代码（如 "en"、"ja"），用于提示词中说明译文来源
    chapters     : ParsedWork.chapters（章节边界列表），chapter 模式时使用
    profile      : 由 get_profile_config() 返回的方案配置字典（可选）。
                   不为 None 时优先从方案中取 agent 配置，否则沿用旧版逻辑。

    说明
    ----
    - skip_polish=True 时完全跳过，不修改任何 block
    - 只润色有译文的块；无译文的块直接跳过
    - 批次模式由 config.json 的 agents.polisher.polish_batch_mode 控制：
        "paragraph"（默认）: 每批最多 BATCH_SIZE 段
        "chapter": 每章一批（需要 chapters 参数）
        "full": 全文一批（超限自动降级）
    - 分隔符不匹配时自动降级为逐段润色
    - 润色结果直接覆盖 translation 字段（不保留原始译文）
    """
    if skip_polish:
        print("[润色] 已跳过（skip_polish=True）。")
        return

    if not blocks:
        return

    # 先统计有译文的块，若无则直接跳过（避免无谓的 get_client 调用）
    translatable = [b for b in blocks if b.translation and b.translation.strip()]
    if not translatable:
        print("[润色] 没有可润色的段落（所有块均无译文），跳过。")
        return

    # 获取 LLM 客户端（确认有工作要做后再初始化）
    if get_client is None:
        raise ImportError(
            "llm_config 模块未找到，请确认项目根目录下存在 llm_config.py。"
        )
    client, agent_cfg = get_client(agent, profile_config=profile)
    # 注入 agent 名称，供 _call_llm 写日志时使用
    agent_cfg = dict(agent_cfg)
    agent_cfg["_agent_name"] = agent

    # 从 config 读取批次模式、自定义提示词和超时时间（默认 paragraph / 60000 / 120s）
    # 若使用 profile，则从 profile 的 polisher 配置中读取，否则从 config.json 的 agents 字段读取
    batch_mode: str = "paragraph"
    token_limit: int = 60000
    custom_prompt: str | None = None
    llm_timeout: int = 120
    try:
        if profile is not None and "polisher" in profile:
            # profile 配置：polish_batch_mode / polish_context_token_limit / system_prompt / timeout
            pcfg = profile.get("polisher", {})
            batch_mode = pcfg.get("polish_batch_mode", "paragraph")
            token_limit = int(pcfg.get("polish_context_token_limit", 60000))
            custom_prompt = pcfg.get("system_prompt") or None
            llm_timeout = int(pcfg.get("timeout", 120))
        elif get_agent_config is not None:
            cfg = get_agent_config(agent)
            batch_mode = cfg.get("polish_batch_mode", "paragraph")
            token_limit = int(cfg.get("polish_context_token_limit", 60000))
            custom_prompt = cfg.get("system_prompt") or None
            llm_timeout = int(cfg.get("timeout", 120))
    except Exception:
        pass  # 读取失败时静默回退为 paragraph 模式

    # 构建润色提示词（优先使用 config.json 中的自定义提示词）
    lang_name = _get_lang_name(source_lang)
    system_prompt = custom_prompt if custom_prompt else _SYSTEM_PROMPT_TEMPLATE.format(source_lang=lang_name)

    print(
        f"[润色] 共 {len(translatable)} 段有译文，批次模式：{batch_mode}..."
    )

    if batch_mode == "full":
        _polish_full(blocks, client, agent_cfg, system_prompt, token_limit, timeout=llm_timeout)
    elif batch_mode == "chapter":
        if chapters:
            _polish_chapter_mode(chapters, client, agent_cfg, system_prompt, token_limit, timeout=llm_timeout)
        else:
            print("[润色] chapter 模式需要章节数据，降级为 paragraph 模式。")
            _polish_paragraph_mode(blocks, client, agent_cfg, system_prompt, timeout=llm_timeout)
    else:
        # paragraph 模式（默认）
        _polish_paragraph_mode(blocks, client, agent_cfg, system_prompt, timeout=llm_timeout)

    print(f"[润色] 完成，共润色 {len(translatable)} 段。")


def polish_work(
    blocks: list,
    agent: str = "polisher",
    skip_polish: bool = False,
    source_lang: str = "en",
    chapters: list[list] | None = None,
    profile: dict | None = None,
) -> None:
    """
    polish_blocks 的别名，供 main.py 统一调用（接口与计划书一致）。
    """
    polish_blocks(
        blocks, agent=agent, skip_polish=skip_polish,
        source_lang=source_lang, chapters=chapters, profile=profile,
    )


# ---------------------------------------------------------------------------
# CLI 快速测试入口（python polisher.py <html_path>）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("polisher.py — 直接运行模式（快速测试）")
    print()

    if len(sys.argv) < 2:
        print("用法：python polisher.py <AO3_HTML文件路径> [agent名称]")
        print("示例：python polisher.py test/Tease_Test_Taste.html polisher")
        sys.exit(1)

    html_path = sys.argv[1]
    agent_name = sys.argv[2] if len(sys.argv) > 2 else "polisher"

    try:
        from html_parser import parse_ao3_html
        from dict_manager import load_dict
        from translator import translate_work
    except ImportError as e:
        print(f"[错误] 无法导入依赖模块：{e}")
        sys.exit(1)

    print(f"正在解析：{html_path}")
    try:
        work = parse_ao3_html(html_path)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"解析完成：正文 {len(work.body)} 段")

    # 加载通用词典
    from pathlib import Path
    general_path = Path(html_path).parent.parent / "dicts" / "general.json"
    term_map: dict[str, str] = {}
    if general_path.exists():
        try:
            term_data = load_dict(str(general_path))
            term_map = term_data.get("terms", {})
            print(f"已加载词典：{len(term_map)} 条术语")
        except Exception as e:
            print(f"[警告] 加载词典失败：{e}，将不使用术语约束")

    # 只处理前 2 段（演示模式）
    demo_blocks = work.body[:2]
    print(f"\n（演示模式：仅处理前 {len(demo_blocks)} 段正文）")

    print("\n[步骤 1/2] 翻译...")
    try:
        translate_work(demo_blocks, term_map=term_map, agent="translator")
    except (ImportError, EnvironmentError, KeyError) as e:
        print(f"[错误] 翻译失败：{e}")
        sys.exit(1)

    print("\n[步骤 2/2] 润色...")
    try:
        polish_work(demo_blocks, agent=agent_name)
    except (ImportError, EnvironmentError, KeyError) as e:
        print(f"[错误] 润色失败：{e}")
        sys.exit(1)

    print()
    for i, block in enumerate(demo_blocks, 1):
        print(f"--- 第 {i} 段 ---")
        print(f"原文：{block.text[:100]}{'...' if len(block.text) > 100 else ''}")
        print(f"润色后译文：{block.translation[:100]}{'...' if len(block.translation) > 100 else ''}")
        print()
