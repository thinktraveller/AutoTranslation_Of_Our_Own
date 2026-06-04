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
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# get_client / get_agent_config 在模块顶层引用，使 patch("polisher.get_client") 生效。
try:
    from .llm_config import get_client
except ImportError:
    get_client = None  # type: ignore[assignment]

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

_SYSTEM_PROMPT = """\
你是一名资深的简体中文同人文编辑，请对以下已翻译的文本进行润色：
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


def _call_llm(text: str, client, agent_cfg: dict) -> str | None:
    """
    向 LLM 发送润色请求，返回润色后的文本字符串。
    带指数退避重试（最多 MAX_RETRIES 次）。
    所有重试均失败时返回 None。
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=agent_cfg["model"],
                temperature=agent_cfg["temperature"],
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2, 4 秒
                print(f"  [润色] 第 {attempt} 次请求失败：{e}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"  [润色] 请求失败（已重试 {MAX_RETRIES} 次）：{e}")
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
        print(f"  批次 {batch_index}/{total_batches}（1 段）...", end=" ", flush=True)
        result = _call_llm(valid[0].translation, client, agent_cfg)
        if result is not None:
            valid[0].translation = result
            print("完成")
        else:
            print("失败，保留原译文")
        return

    # 多段合并润色
    combined = f"\n\n{PARAGRAPH_SEP}\n\n".join(b.translation for b in valid)
    print(
        f"  批次 {batch_index}/{total_batches}（{len(valid)} 段，{len(combined)} 字符）...",
        end=" ",
        flush=True,
    )
    raw_result = _call_llm(combined, client, agent_cfg)

    if raw_result is None:
        print("失败，批次降级为逐段润色...")
        _fallback_polish_one_by_one(valid, client, agent_cfg)
        return

    # 按分隔符拆分润色结果
    parts = [p.strip() for p in raw_result.split(PARAGRAPH_SEP)]

    if len(parts) != len(valid):
        print(
            f"段落数不匹配（期望 {len(valid)}，实际 {len(parts)}），降级为逐段润色..."
        )
        _fallback_polish_one_by_one(valid, client, agent_cfg)
        return

    for block, polished_text in zip(valid, parts):
        block.translation = polished_text
    print("完成")


def _fallback_polish_one_by_one(
    batch: list,
    client,
    agent_cfg: dict,
) -> None:
    """降级方案：对批次中每段逐一单独润色。"""
    for i, block in enumerate(batch, 1):
        if not block.translation or not block.translation.strip():
            continue
        print(f"    降级润色第 {i}/{len(batch)} 段...", end=" ", flush=True)
        result = _call_llm(block.translation, client, agent_cfg)
        if result is not None:
            block.translation = result
            print("完成")
        else:
            print("失败，保留原译文")


# ---------------------------------------------------------------------------
# 公开 API：润色
# ---------------------------------------------------------------------------


def polish_blocks(
    blocks: list,
    agent: str = "polisher",
    skip_polish: bool = False,
) -> None:
    """
    对 TranslatableBlock 列表进行润色，就地覆盖每个 block 的 translation 字段。

    参数
    ----
    blocks       : TranslatableBlock 列表（来自 html_parser，已完成翻译）
    agent        : 使用的 agent 名称（对应 config.json 中的配置）
    skip_polish  : 若为 True，立即返回，不调用 LLM（对应 --skip-polish 参数）

    说明
    ----
    - skip_polish=True 时完全跳过，不修改任何 block
    - 只润色有译文的块；无译文的块直接跳过
    - 每批最多 BATCH_SIZE（10）段，超出则自动分批
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
    client, agent_cfg = get_client(agent)

    print(
        f"[润色] 共 {len(translatable)} 段有译文，分批润色中（每批最多 {BATCH_SIZE} 段）..."
    )

    # 按原始顺序分批（以 blocks 为基准，保持批次与翻译模块一致）
    total_batches = (len(translatable) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(translatable), BATCH_SIZE):
        batch = translatable[i : i + BATCH_SIZE]
        batch_index = i // BATCH_SIZE + 1
        _polish_batch(batch, client, agent_cfg, batch_index, total_batches)

    print(f"[润色] 完成，共润色 {len(translatable)} 段。")


def polish_work(
    blocks: list,
    agent: str = "polisher",
    skip_polish: bool = False,
) -> None:
    """
    polish_blocks 的别名，供 main.py 统一调用（接口与计划书一致）。
    """
    polish_blocks(blocks, agent=agent, skip_polish=skip_polish)


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
