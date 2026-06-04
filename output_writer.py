"""
output_writer.py — 输出模块：txt / Markdown / docx 三种格式

输出路径规则：与输入文件同目录，文件名强制使用纯 ASCII（英文）以规避 Windows 编码问题。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from html_parser import ParsedWork


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------

def _safe_stem(input_path: str | Path) -> str:
    """
    将输入文件名主干转换为纯 ASCII 安全名称。
    移除所有非 ASCII 字符；若结果为空则回退为 'work'。
    """
    stem = Path(input_path).stem
    ascii_stem = re.sub(r'[^\x20-\x7E]', '', stem).strip()
    ascii_stem = re.sub(r'\s+', '_', ascii_stem)
    return ascii_stem if ascii_stem else 'work'


def get_output_paths(input_path: str | Path) -> dict[str, Path]:
    """
    返回三种输出格式的完整路径，均与输入文件同目录，文件名为纯 ASCII。
    """
    p = Path(input_path).resolve()
    stem = _safe_stem(p)
    base_name = stem + '_translated'
    parent = p.parent
    return {
        'txt':  parent / f'{base_name}.txt',
        'md':   parent / f'{base_name}.md',
        'docx': parent / f'{base_name}.docx',
    }


# ---------------------------------------------------------------------------
# txt 输出
# ---------------------------------------------------------------------------

def write_txt(result: ParsedWork, output_path: str | Path) -> None:
    """将正文译文写出为纯文本，段落间以空行分隔。"""
    lines = [block.translation for block in result.body if block.translation]
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(lines))
    print(f'[输出] txt 已生成：{output_path}')


# ---------------------------------------------------------------------------
# 中途暂停与精校回填
# ---------------------------------------------------------------------------

def pause_for_proofread(txt_path: str | Path) -> list[str]:
    """
    中途暂停，等待用户精校 txt 文件，读取后返回段落列表。
    """
    print(f'\n[步骤完成] 正文 txt 已生成：{txt_path}')
    print('请打开 txt 文件进行正文精校。精校完成后，按回车键继续生成 Markdown 和 docx...')
    input()
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return [p.strip() for p in content.split('\n\n') if p.strip()]


# ---------------------------------------------------------------------------
# Markdown 输出
# ---------------------------------------------------------------------------

def write_markdown(
    result: ParsedWork,
    output_path: str | Path,
    proofread_paragraphs: Optional[list[str]] = None,
) -> None:
    """
    生成 Markdown 文件，包含标签、摘要、前言备注、精校正文、尾注。
    若提供 proofread_paragraphs，正文使用精校内容；否则使用 result.body 的 translation。
    """
    lines: list[str] = []

    lines.append(f'# {result.title}')
    lines.append('')
    lines.append(f'**作者**：{result.author}')
    lines.append('')

    if result.tags:
        lines.append('## 标签信息')
        lines.append('')
        for block in result.tags:
            text = block.translation if block.translation else block.text
            lines.append(f'- {text}')
        lines.append('')

    if result.summary:
        lines.append('## 摘要')
        lines.append('')
        for block in result.summary:
            text = block.translation if block.translation else block.text
            lines.append(text)
            lines.append('')

    if result.notes:
        lines.append('## 前言备注')
        lines.append('')
        for block in result.notes:
            text = block.translation if block.translation else block.text
            lines.append(text)
            lines.append('')

    lines.append('## 正文')
    lines.append('')
    body_texts: list[str]
    if proofread_paragraphs is not None:
        body_texts = proofread_paragraphs
    else:
        body_texts = [b.translation if b.translation else b.text for b in result.body]
    for para in body_texts:
        if para:
            lines.append(para)
            lines.append('')

    if result.endnotes:
        lines.append('## 尾注')
        lines.append('')
        for block in result.endnotes:
            text = block.translation if block.translation else block.text
            lines.append(text)
            lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[输出] Markdown 已生成：{output_path}')


# ---------------------------------------------------------------------------
# docx 输出（pandoc）
# ---------------------------------------------------------------------------

def write_docx(md_path: str | Path, docx_path: str | Path) -> None:
    """
    调用 pandoc 将 Markdown 转换为 docx。
    通过 cwd=文件所在目录 + 纯文件名参数规避 Windows 路径编码问题。
    输入输出文件名已为纯 ASCII，不存在编码风险。
    """
    md = Path(md_path).resolve()
    docx = Path(docx_path).resolve()

    assert md.exists(), f'输入文件不存在：{md}'

    try:
        proc = subprocess.run(
            ['pandoc', md.name, '-o', docx.name],
            cwd=str(md.parent),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr)
        print(f'[输出] docx 已生成：{docx_path}')
    except FileNotFoundError:
        print('[错误] 未找到 pandoc，请先安装：winget install JohnMacFarlane.Pandoc')
        raise
    except Exception as e:
        print(f'[警告] pandoc 转换失败：{e}')
        print('可手动执行：')
        print(f'  cd "{md.parent}"')
        print(f'  pandoc "{md.name}" -o "{docx.name}"')
        raise


# ---------------------------------------------------------------------------
# 完整输出流程
# ---------------------------------------------------------------------------

def write_all(
    result: ParsedWork,
    input_path: str | Path,
    *,
    skip_pause: bool = False,
) -> dict[str, Path]:
    """
    完整三步输出流程：
      1. 写 txt
      2. 暂停等待用户精校（skip_pause=True 时跳过，用于测试）
      3. 读取精校结果，回填 result.body
      4. 写 Markdown
      5. pandoc → docx
    返回包含 txt/md/docx 三个输出路径的字典。
    """
    paths = get_output_paths(input_path)

    write_txt(result, paths['txt'])

    if skip_pause:
        proofread_paragraphs = [b.translation for b in result.body if b.translation]
    else:
        proofread_paragraphs = pause_for_proofread(paths['txt'])
        body_count = sum(1 for b in result.body if b.translation)
        if len(proofread_paragraphs) != body_count:
            print(
                f'[警告] 精校后段落数（{len(proofread_paragraphs)}）'
                f'与原始正文段落数（{body_count}）不一致。'
            )
            cont = input('是否继续？(y/n): ').strip().lower()
            if cont != 'y':
                print('已取消。txt 文件保留，md 和 docx 未生成。')
                return paths
        for i, block in enumerate(result.body):
            if i < len(proofread_paragraphs):
                block.translation = proofread_paragraphs[i]

    write_markdown(result, paths['md'], proofread_paragraphs=proofread_paragraphs)
    write_docx(paths['md'], paths['docx'])

    print('\n[完成] 三种格式已全部生成：')
    print(f'  txt  → {paths["txt"]}')
    print(f'  md   → {paths["md"]}')
    print(f'  docx → {paths["docx"]}')

    return paths
