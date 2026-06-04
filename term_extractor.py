"""
term_extractor.py — 术语提取 agent 与 CLI 确认流程

功能：
  1. extract_terms(blocks, existing_terms, agent) -> list[ExtractedTerm]
     调用 LLM 对文本块列表进行术语扫描，跳过已在词典中的词条，
     正文较长时自动分批发送（每批不超过 BATCH_CHAR_LIMIT 字符）。

  2. run_cli_confirm(terms) -> dict[str, str]
     逐条在 CLI 中展示术语，让用户决定是否加入词典、是否修改译名。
     返回已确认的 {原文: 译文} 映射。

  3. extract_and_confirm(blocks, existing_terms, agent) -> dict[str, str]
     整合函数：提取 + 用户确认，供 main.py 调用。

用法（作为模块导入）：
    from html_parser import parse_ao3_html
    from dict_manager import load_dict, merge_dicts
    from term_extractor import extract_and_confirm

    work = parse_ao3_html("test/example.html")
    general = load_dict("dicts/general.json")
    existing = merge_dicts(general)
    confirmed = extract_and_confirm(work.body, existing)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# get_client 在模块顶层引用，使 patch("term_extractor.get_client") 生效。
# 若 llm_config 或 openai SDK 未安装，延迟到实际调用时再报错。
try:
    from llm_config import get_client
except ImportError:
    get_client = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 每批发送给 LLM 的最大字符数（约 1500-2000 tokens）
BATCH_CHAR_LIMIT = 3000

# LLM 请求失败时的最大重试次数
MAX_RETRIES = 3

# 术语提取系统提示词
_SYSTEM_PROMPT = """\
你是一名专业的同人文翻译助手。请从以下文本中提取所有需要统一译名的术语，包括：
- 人物名称（主角、配角、提及到的任何角色）
- 地名、组织名、机构名
- 该 IP 或同人圈中有约定俗成译名的专有词汇
- 特定称谓、头衔、职位名

对于每个术语，请给出：
1. 原文（original）
2. 推荐的中文译名（suggested_translation）
3. 简短说明（note）：该术语的身份/含义（一句话即可）

只提取专有名词，不提取普通英语单词。
以 JSON 数组格式返回，每项包含字段：original, suggested_translation, note
若文本中没有需要提取的术语，返回空数组 []
除 JSON 数组本身外，不要输出任何其他内容。\
"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ExtractedTerm:
    """LLM 提取出的单条术语。"""
    original: str                   # 原文
    suggested_translation: str      # LLM 推荐译名
    note: str = ""                  # 说明（身份/含义）


# ---------------------------------------------------------------------------
# 内部辅助：LLM 调用
# ---------------------------------------------------------------------------

def _call_llm_for_terms(text: str, client, agent_cfg: dict) -> list[ExtractedTerm]:
    """
    向 LLM 发送单批文本，解析并返回术语列表。
    若 LLM 响应格式不合法，打印警告并返回空列表（不抛异常）。
    内置指数退避重试（最多 MAX_RETRIES 次）。
    """
    import time

    last_exception = None
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
            raw = response.choices[0].message.content.strip()
            break  # 成功，跳出重试循环
        except Exception as e:
            last_exception = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2, 4 秒
                print(f"  [术语提取] 第 {attempt} 次请求失败：{e}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"  [术语提取] 请求失败（已重试 {MAX_RETRIES} 次）：{e}")
                return []
    else:
        # 所有重试均失败（理论上不会走到这里，但保险起见）
        print(f"  [术语提取] 所有重试均失败：{last_exception}")
        return []

    # 尝试从响应中提取 JSON 数组
    # LLM 有时会在 JSON 前后附加 ```json ... ``` 代码块标记，需清理
    json_text = _extract_json_array(raw)
    if json_text is None:
        print(f"  [术语提取] 无法从响应中解析 JSON，已跳过本批。")
        print(f"  原始响应（前200字）：{raw[:200]}")
        return []

    try:
        items = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  [术语提取] JSON 解析失败：{e}，已跳过本批。")
        print(f"  原始响应（前200字）：{raw[:200]}")
        return []

    if not isinstance(items, list):
        print(f"  [术语提取] LLM 返回了非数组格式，已跳过本批。")
        return []

    terms: list[ExtractedTerm] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()
        suggested = str(item.get("suggested_translation", "")).strip()
        note = str(item.get("note", "")).strip()
        if original and suggested:
            terms.append(ExtractedTerm(
                original=original,
                suggested_translation=suggested,
                note=note,
            ))
    return terms


def _extract_json_array(text: str) -> str | None:
    """
    从 LLM 响应文本中提取 JSON 数组字符串。
    处理以下情况：
      - 纯 JSON 数组
      - ```json\n...\n``` 代码块
      - 响应前后有多余文字
    """
    # 先尝试去除 markdown 代码块标记
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block:
        text = code_block.group(1).strip()

    # 找到第一个 [ 到最后一个 ] 之间的内容
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start:end + 1]


# ---------------------------------------------------------------------------
# 公开 API：术语提取
# ---------------------------------------------------------------------------

def extract_terms(
    blocks: list,
    existing_terms: dict[str, str] | None = None,
    agent: str = "term_extractor",
) -> list[ExtractedTerm]:
    """
    对文本块列表调用 LLM 进行术语提取。

    参数
    ----
    blocks        : TranslatableBlock 列表（来自 html_parser）
    existing_terms: 已有词典映射 {原文: 译文}，已存在的词条自动跳过
    agent         : 使用的 agent 名称（对应 config.json 中的配置）

    返回
    ----
    list[ExtractedTerm]：去重后的术语列表（排除已在词典中的词条）

    说明
    ----
    - 正文较长时自动分批（每批不超过 BATCH_CHAR_LIMIT 字符）
    - 所有批次结果汇总后去重（按 original 字段）
    - 已在 existing_terms 中的词条自动排除
    """
    if not blocks:
        return []

    existing_terms = existing_terms or {}

    # 获取 LLM 客户端
    if get_client is None:
        raise ImportError(
            "llm_config 模块未找到，请确认项目根目录下存在 llm_config.py。"
        )
    try:
        client, agent_cfg = get_client(agent)
    except (ImportError, EnvironmentError, KeyError) as e:
        print(f"[术语提取] 无法初始化 LLM 客户端：{e}")
        raise

    # 将所有块的文本合并，再按 BATCH_CHAR_LIMIT 切分批次
    all_texts = [b.text for b in blocks if b.text.strip()]
    batches = _split_into_batches(all_texts, BATCH_CHAR_LIMIT)

    total_batches = len(batches)
    print(f"[术语提取] 共 {len(all_texts)} 个文本块，分 {total_batches} 批发送给 LLM...")

    all_terms: list[ExtractedTerm] = []
    for i, batch_text in enumerate(batches, 1):
        print(f"  处理第 {i}/{total_batches} 批（{len(batch_text)} 字符）...", end=" ", flush=True)
        terms = _call_llm_for_terms(batch_text, client, agent_cfg)
        print(f"提取到 {len(terms)} 条术语")
        all_terms.extend(terms)

    # 去重：按 original 字段，保留首次出现的条目
    seen: set[str] = set()
    deduped: list[ExtractedTerm] = []
    for t in all_terms:
        key = t.original.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    # 排除已在词典中的词条（精确匹配 + 大小写不敏感匹配）
    existing_lower = {k.lower() for k in existing_terms}
    filtered = [
        t for t in deduped
        if t.original.lower() not in existing_lower
    ]

    skipped = len(deduped) - len(filtered)
    if skipped > 0:
        print(f"[术语提取] 已跳过 {skipped} 条词典中已存在的词条")

    print(f"[术语提取] 最终待确认术语：{len(filtered)} 条")
    return filtered


def _split_into_batches(texts: list[str], char_limit: int) -> list[str]:
    """
    将文本列表分批，每批合并后不超过 char_limit 字符。
    段落之间用换行分隔。
    返回每批的合并字符串列表。
    """
    if not texts:
        return []

    batches: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for text in texts:
        text_len = len(text)
        # 若单段本身超过限制，仍单独作为一批（不拆分段落内部）
        if current_len + text_len > char_limit and current_parts:
            batches.append("\n\n".join(current_parts))
            current_parts = []
            current_len = 0
        current_parts.append(text)
        current_len += text_len

    if current_parts:
        batches.append("\n\n".join(current_parts))

    return batches


# ---------------------------------------------------------------------------
# 公开 API：CLI 确认流程
# ---------------------------------------------------------------------------

def run_cli_confirm(terms: list[ExtractedTerm]) -> dict[str, str]:
    """
    逐条在 CLI 中展示术语，让用户决定是否加入词典。

    交互流程（每条术语）：
      1. 展示原文、推荐译名、说明
      2. 询问：是否加入词典？(y/n/s)
         - y：加入词典
         - n：跳过此条（不加入）
         - s：跳过剩余所有条目（停止确认）
      3. 若选 y，询问：是否修改译名？
         - 直接回车：使用推荐译名
         - 输入新译名：使用用户输入的译名

    返回
    ----
    dict[str, str]：用户确认加入的 {原文: 译名} 映射
    """
    if not terms:
        print("[术语确认] 没有需要确认的术语。")
        return {}

    confirmed: dict[str, str] = {}
    total = len(terms)

    print()
    print("=" * 60)
    print(f"  术语确认流程（共 {total} 条）")
    print("  输入 y 加入词典，n 跳过，s 跳过剩余所有条目")
    print("=" * 60)

    for idx, term in enumerate(terms, 1):
        print()
        print(f"[{idx}/{total}]  术语：{term.original}")
        print(f"        推荐译名：{term.suggested_translation}")
        if term.note:
            print(f"        说明：{term.note}")

        # 询问是否加入词典
        while True:
            answer = input("  是否加入词典？(y/n/s): ").strip().lower()
            if answer in ("y", "n", "s"):
                break
            print("  请输入 y、n 或 s。")

        if answer == "s":
            skipped = total - idx
            if skipped > 0:
                print(f"\n  已跳过剩余 {skipped} 条术语。")
            break

        if answer == "n":
            print(f"  已跳过：{term.original}")
            continue

        # answer == "y"，询问是否修改译名
        final_name = _ask_translation(term.suggested_translation)
        confirmed[term.original] = final_name
        print(f"  已添加：{term.original}  ->  {final_name}")

    print()
    print(f"[术语确认] 完成，共确认 {len(confirmed)} 条术语加入词典。")
    return confirmed


def _ask_translation(default: str) -> str:
    """
    询问用户是否修改译名，返回最终译名。
    直接回车则使用默认值。
    """
    user_input = input(
        f"  译名（回车使用「{default}」，或直接输入新译名）: "
    ).strip()
    return user_input if user_input else default


# ---------------------------------------------------------------------------
# 公开 API：整合函数
# ---------------------------------------------------------------------------

def extract_and_confirm(
    blocks: list,
    existing_terms: dict[str, str] | None = None,
    agent: str = "term_extractor",
) -> dict[str, str]:
    """
    完整流程：术语提取 + CLI 用户确认。
    返回用户确认加入词典的 {原文: 译名} 映射。

    参数
    ----
    blocks        : TranslatableBlock 列表
    existing_terms: 已有词典映射，用于过滤重复词条
    agent         : LLM agent 名称

    返回
    ----
    dict[str, str]：用户确认的新词条，调用方负责将其写入词典。
    """
    terms = extract_terms(blocks, existing_terms=existing_terms, agent=agent)

    if not terms:
        print("[术语提取] 未提取到新术语，跳过确认流程。")
        return {}

    return run_cli_confirm(terms)


# ---------------------------------------------------------------------------
# CLI 快速测试入口（python term_extractor.py）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("term_extractor.py — 直接运行模式（快速测试）")
    print()

    # 检查是否提供了 HTML 文件路径
    if len(sys.argv) < 2:
        print("用法：python term_extractor.py <AO3_HTML文件路径> [agent名称]")
        print("示例：python term_extractor.py test/Tease_Test_Taste.html term_extractor")
        sys.exit(1)

    html_path = sys.argv[1]
    agent_name = sys.argv[2] if len(sys.argv) > 2 else "term_extractor"

    # 导入解析模块
    try:
        from html_parser import parse_ao3_html
    except ImportError as e:
        print(f"[错误] 无法导入 html_parser：{e}")
        sys.exit(1)

    # 解析 HTML
    print(f"正在解析：{html_path}")
    try:
        work = parse_ao3_html(html_path)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"解析完成：正文 {len(work.body)} 段，标签 {len(work.tags)} 条")
    print()

    # 只取前 10 段进行演示（避免消耗过多 API 调用）
    demo_blocks = work.body[:10]
    print(f"（演示模式：仅使用前 {len(demo_blocks)} 段正文）")

    # 运行提取 + 确认
    try:
        confirmed = extract_and_confirm(demo_blocks, agent=agent_name)
    except (ImportError, EnvironmentError, KeyError) as e:
        print(f"[错误] {e}")
        sys.exit(1)

    if confirmed:
        print()
        print("已确认加入词典的术语：")
        for orig, trans in confirmed.items():
            print(f"  {orig}  ->  {trans}")
    else:
        print("未确认任何术语。")
