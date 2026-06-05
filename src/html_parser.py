"""
html_parser.py — AO3 HTML 解析模块

将 AO3 标准 HTML 文件拆分为结构化数据，区分可翻译文本块与需保留的内容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    raise ImportError(
        "beautifulsoup4 未安装。请在虚拟环境中运行：\n"
        "  pip install beautifulsoup4 lxml -i https://pypi.tuna.tsinghua.edu.cn/simple"
    )


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class TranslatableBlock:
    """代表一个可翻译的文本单元。"""

    block_id: str          # 唯一标识符，用于回填译文
    text: str              # 原文（纯文本，供 LLM 翻译）
    translation: str = ""  # 译文（翻译后填充）
    source: str = ""       # 来源区域标识，例如 "body" / "tags" / "summary" / "notes" / "endnotes"


@dataclass
class ParsedWork:
    """解析后的完整作品结构。"""

    title: str                              # 作品标题（原文保留）
    author: str                             # 作者名（原文保留，不翻译）
    tags: list[TranslatableBlock]           # 标签 dd 内容（需翻译）
    summary: list[TranslatableBlock]        # 摘要段落
    notes: list[TranslatableBlock]          # 前言备注段落
    body: list[TranslatableBlock]           # 正文段落列表
    endnotes: list[TranslatableBlock]       # 尾注段落
    raw_html: str                           # 原始 HTML，保留用于最终输出重建
    source_url: str = ""                    # AO3 原文链接（解析失败时为空字符串）
    chapters: list[list[TranslatableBlock]] = field(default_factory=list)
    # 章节边界列表，每个元素是一章的 TranslatableBlock 列表（切分自 body）
    # 单章作品时 chapters = [body]；多章时按 AO3 章节容器拆分


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _make_id(prefix: str, index: int) -> str:
    """生成格式化的块 ID，例如 body_0001。"""
    return f"{prefix}_{index:04d}"


def _extract_text(tag: Tag) -> str:
    """提取标签内的可见纯文本，折叠多余空白。"""
    text = tag.get_text(separator=" ", strip=True)
    # 折叠连续空白（含换行）
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _blocks_from_userstuff(container: Tag, source: str, id_prefix: str) -> list[TranslatableBlock]:
    """
    从一个 .userstuff 容器中提取所有 <p> 的文本，返回 TranslatableBlock 列表。
    跳过空白段落（仅含空格或不可见字符）。
    """
    blocks: list[TranslatableBlock] = []
    paragraphs = container.find_all("p")

    if not paragraphs:
        # 没有 <p> 时，整体当作一个块
        text = _extract_text(container)
        if text:
            blocks.append(TranslatableBlock(
                block_id=_make_id(id_prefix, 0),
                text=text,
                source=source,
            ))
        return blocks

    for idx, p in enumerate(paragraphs):
        text = _extract_text(p)
        if not text:
            continue  # 跳过空段落（AO3 中常见 <p> </p> 空行）
        blocks.append(TranslatableBlock(
            block_id=_make_id(id_prefix, idx),
            text=text,
            source=source,
        ))
    return blocks


# ---------------------------------------------------------------------------
# 主解析函数
# ---------------------------------------------------------------------------

def parse_ao3_html(html_path: str | Path) -> ParsedWork:
    """
    解析 AO3 标准 HTML 文件，返回 ParsedWork 结构化对象。

    参数
    ----
    html_path : str 或 Path
        AO3 HTML 文件的路径（绝对或相对路径均可）。

    返回
    ----
    ParsedWork
        包含标题、作者、标签、摘要、备注、正文、尾注及原始 HTML。

    异常
    ----
    FileNotFoundError
        指定路径不存在。
    ValueError
        文件内容无法解析为有效的 AO3 HTML 结构。
    """
    html_path = Path(html_path)
    if not html_path.exists():
        raise FileNotFoundError(f"HTML 文件不存在：{html_path}")

    raw_html = html_path.read_text(encoding="utf-8")

    # 优先使用 lxml，降级到 html.parser
    try:
        soup = BeautifulSoup(raw_html, "lxml")
    except Exception:
        soup = BeautifulSoup(raw_html, "html.parser")

    # ------------------------------------------------------------------
    # 1. 标题
    # ------------------------------------------------------------------
    title_tag = soup.select_one(".meta h1")
    title = _extract_text(title_tag) if title_tag else "(未找到标题)"

    # ------------------------------------------------------------------
    # 2. 作者（保留原文，不翻译）
    # ------------------------------------------------------------------
    byline_tag = soup.select_one("div.byline")
    author = _extract_text(byline_tag) if byline_tag else "(未找到作者)"
    author = re.sub(r'^by\s+', '', author, flags=re.IGNORECASE)

    # ------------------------------------------------------------------
    # 3. 标签 dd（跳过 Stats 区域）
    # ------------------------------------------------------------------
    tags: list[TranslatableBlock] = []
    dl_tag = soup.select_one("dl.tags")
    if dl_tag:
        skip_next_dd = False
        for child in dl_tag.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "dt":
                # 检测到 "Stats:" 或 "Language:" 标签，下一个 dd 跳过
                dt_text = _extract_text(child).lower()
                skip_next_dd = "stats" in dt_text or "language" in dt_text
            elif child.name == "dd":
                if skip_next_dd:
                    skip_next_dd = False
                    continue
                text = _extract_text(child)
                if text:
                    tags.append(TranslatableBlock(
                        block_id=_make_id("tag", len(tags)),
                        text=text,
                        source="tags",
                    ))

    # ------------------------------------------------------------------
    # 4. 摘要（preface 内 blockquote.userstuff）
    # ------------------------------------------------------------------
    summary: list[TranslatableBlock] = []
    preface_div = soup.select_one("#preface")
    if preface_div:
        # 精确定位：preface 内 .meta 内 blockquote.userstuff
        summary_bq = preface_div.select_one(".meta > blockquote.userstuff")
        if summary_bq is None:
            # 容错：直接找 preface 内第一个 blockquote.userstuff
            summary_bq = preface_div.select_one("blockquote.userstuff")
        if summary_bq:
            summary = _blocks_from_userstuff(summary_bq, "summary", "summary")

    # ------------------------------------------------------------------
    # 5. 前言备注（preface 内 div.notes blockquote，或同级 div blockquote）
    # ------------------------------------------------------------------
    notes: list[TranslatableBlock] = []
    if preface_div:
        # AO3 备注区域有多种结构，逐一尝试
        notes_bq = preface_div.select_one("div.notes blockquote.userstuff")
        if notes_bq is None:
            # 容错：找摘要 blockquote 之外其他 blockquote.userstuff
            all_bqs = preface_div.select("blockquote.userstuff")
            summary_bq_ref = preface_div.select_one("blockquote.userstuff")
            extra_bqs = [bq for bq in all_bqs if bq is not summary_bq_ref]
            if extra_bqs:
                notes_bq = extra_bqs[0]
        if notes_bq:
            notes = _blocks_from_userstuff(notes_bq, "notes", "note")

    # ------------------------------------------------------------------
    # 6. 正文（#chapters 内 .userstuff p）及章节边界
    # ------------------------------------------------------------------
    body: list[TranslatableBlock] = []
    chapters_list: list[list[TranslatableBlock]] = []
    chapters_div = soup.select_one("#chapters")
    if chapters_div:
        # AO3 多章：每章在独立的 div[id^="chapter-"] 容器内
        chapter_containers = chapters_div.select("div[id^='chapter-']")
        if chapter_containers:
            # 多章文件：分章解析
            for ch_idx, ch_div in enumerate(chapter_containers):
                userstuff_div = ch_div.select_one("div.userstuff")
                if userstuff_div is None:
                    userstuff_div = ch_div
                ch_blocks = _blocks_from_userstuff(
                    userstuff_div, "body", f"body_ch{ch_idx:02d}"
                )
                chapters_list.append(ch_blocks)
                body.extend(ch_blocks)
        else:
            # 单章文件（最常见）
            userstuff_div = chapters_div.select_one("div.userstuff")
            if userstuff_div is None:
                userstuff_div = chapters_div  # 容错：整个 chapters 块
            body = _blocks_from_userstuff(userstuff_div, "body", "body")
            chapters_list = [body]
    else:
        print("[警告] 未找到 #chapters 元素，正文可能为空")

    # ------------------------------------------------------------------
    # 7. 尾注（#endnotes blockquote.userstuff）
    # ------------------------------------------------------------------
    endnotes: list[TranslatableBlock] = []
    endnotes_div = soup.select_one("#endnotes")
    if endnotes_div:
        endnotes_bq = endnotes_div.select_one("blockquote.userstuff")
        if endnotes_bq:
            endnotes = _blocks_from_userstuff(endnotes_bq, "endnotes", "endnote")
        else:
            # 降级：尝试 div.userstuff，仍无则以整个 #endnotes 为容器
            endnotes_container = endnotes_div.select_one("div.userstuff") or endnotes_div
            endnotes = _blocks_from_userstuff(endnotes_container, "endnotes", "endnote")

    # ------------------------------------------------------------------
    # 8. 原文链接（<link rel="canonical"> 或页面内指向 AO3 作品的链接）
    # ------------------------------------------------------------------
    source_url = ""
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href"):
        source_url = str(canonical_tag["href"])
    if not source_url:
        # 降级：查找页面内第一个指向 archiveofourown.org/works/ 的链接
        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag["href"])
            if "archiveofourown.org/works/" in href:
                source_url = href
                break

    return ParsedWork(
        title=title,
        author=author,
        tags=tags,
        summary=summary,
        notes=notes,
        body=body,
        endnotes=endnotes,
        raw_html=raw_html,
        source_url=source_url,
        chapters=chapters_list,
    )


# ---------------------------------------------------------------------------
# CLI 快速诊断（python html_parser.py <文件路径>）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python html_parser.py <AO3_HTML文件路径>")
        sys.exit(1)

    target = sys.argv[1]
    print(f"正在解析：{target}")
    try:
        work = parse_ao3_html(target)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"\n--- 解析结果摘要 ---")
    print(f"标题       : {work.title}")
    print(f"作者       : {work.author}")
    print(f"标签数     : {len(work.tags)}")
    print(f"摘要段落数 : {len(work.summary)}")
    print(f"前言备注数 : {len(work.notes)}")
    print(f"正文段落数 : {len(work.body)}")
    print(f"尾注段落数 : {len(work.endnotes)}")

    if work.tags:
        print(f"\n--- 标签预览（前3条）---")
        for t in work.tags[:3]:
            print(f"  [{t.block_id}] {t.text}")

    if work.body:
        print(f"\n--- 正文第一段（前120字）---")
        print(f"  {work.body[0].text[:120]}")
