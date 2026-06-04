"""
main.py — ATO3 主流程入口

用法：
    python main.py <html_file> [选项]

选项：
    --source-lang LANG      源语言（默认：en，目前仅用于提示词，不影响流程）
    --general-dict PATH     通用词典路径（默认：dicts/general.json）
    --ip-dict PATH          IP 词典路径（不指定则自动按输入文件名查找或新建）
    --no-general-dict       不加载通用词典
    --skip-polish           跳过润色步骤
    --skip-term-extract     跳过术语提取，直接使用现有词典
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ── Windows UTF-8 模式（必须在其他导入前设置）──────────────────────────────
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONUTF8', '1')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass  # Python < 3.7 fallback，实际不影响 3.10+


from src.html_parser import parse_ao3_html
from src.dict_manager import load_dict, save_dict, merge_dicts
from src.term_extractor import extract_and_confirm
from src.translator import translate_work, verify_terms, save_progress, load_progress
from src.polisher import polish_work
from src.output_writer import write_all, get_output_paths, _safe_stem


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _step(n: int, total: int, desc: str) -> None:
    print(f'\n[{n}/{total}] {desc}')


def _auto_ip_dict_path(input_path: Path) -> Path:
    """根据输入文件名自动推断 IP 词典路径（dicts/ip/{安全词干}.json）。"""
    stem = _safe_stem(input_path) or 'ip'
    return Path(__file__).parent / 'dicts' / 'ip' / f'{stem}.json'


def _load_ip_dict_data(ip_dict_path: Path) -> dict:
    """加载 IP 词典，若不存在则返回空词典结构（不报错）。"""
    if ip_dict_path.exists():
        try:
            return load_dict(ip_dict_path)
        except Exception as e:
            print(f'  [警告] 加载 IP 词典失败：{e}，将使用空词典继续。')
    return {'meta': {'name': ip_dict_path.stem, 'version': '1.0'}, 'terms': {}}


def _save_ip_dict(ip_dict_path: Path, ip_data: dict, new_terms: dict) -> None:
    """将新词条合并到 IP 词典并保存。"""
    if not new_terms:
        return
    ip_dict_path.parent.mkdir(parents=True, exist_ok=True)
    ip_data.setdefault('terms', {}).update(new_terms)
    try:
        save_dict(ip_dict_path, ip_data)
        print(f'  [词典] 已保存 {len(new_terms)} 条新术语到：{ip_dict_path}')
    except Exception as e:
        print(f'  [警告] IP 词典保存失败：{e}')


# ── 参数解析 ──────────────────────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='python main.py',
        description='ATO3 — 自动翻译 AO3 同人文（HTML → txt / Markdown / docx）',
    )
    parser.add_argument('html_file', help='AO3 HTML 文件路径')
    parser.add_argument(
        '--source-lang', default='en', metavar='LANG',
        help='源语言（默认：en）',
    )
    parser.add_argument(
        '--general-dict', default=None, metavar='PATH',
        help='通用词典路径（默认：dicts/general.json）',
    )
    parser.add_argument(
        '--ip-dict', default=None, metavar='PATH',
        help='IP 词典路径（默认：按输入文件名自动推断）',
    )
    parser.add_argument(
        '--no-general-dict', action='store_true',
        help='不加载通用词典',
    )
    parser.add_argument(
        '--skip-polish', action='store_true',
        help='跳过润色步骤',
    )
    parser.add_argument(
        '--skip-term-extract', action='store_true',
        help='跳过术语提取，直接使用现有词典',
    )
    return parser.parse_args(argv)


# ── 主流程 ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    args = _parse_args(argv)

    # ── 步骤计数 ──────────────────────────────────────────────────────────
    # 动态计算总步骤数，供进度提示使用
    total_steps = 8
    if args.skip_term_extract:
        total_steps -= 1
    if args.skip_polish:
        total_steps -= 1
    step_counter = [0]

    def step(desc: str) -> None:
        step_counter[0] += 1
        _step(step_counter[0], total_steps, desc)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. 检查输入文件
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('检查输入文件')
    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f'[错误] 文件不存在：{html_path}')
        return 1
    if not html_path.suffix.lower() in ('.html', '.htm'):
        print(f'[警告] 文件扩展名不是 .html/.htm，仍尝试解析：{html_path}')
    print(f'  输入文件：{html_path.resolve()}')

    # 断点续传文件路径（与输入文件同目录，纯 ASCII 文件名）
    progress_path = html_path.parent / f'{_safe_stem(html_path)}_progress.json'

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. 解析 HTML
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('解析 HTML')
    try:
        work = parse_ao3_html(str(html_path))
    except Exception as e:
        print(f'[错误] HTML 解析失败：{e}')
        return 1

    total_body = len(work.body)
    total_tags = len(work.tags)
    total_summary = len(work.summary)
    total_notes = len(work.notes)
    total_endnotes = len(work.endnotes)
    print(f'  标题：{work.title}')
    print(f'  作者：{work.author}')
    print(
        f'  正文：{total_body} 段'
        f'｜标签：{total_tags} 条'
        f'｜摘要：{total_summary} 段'
        f'｜前言：{total_notes} 段'
        f'｜尾注：{total_endnotes} 段'
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. 加载词典
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('加载词典')

    general_data: dict = {}
    if not args.no_general_dict:
        general_dict_path = Path(
            args.general_dict
            if args.general_dict
            else Path(__file__).parent / 'dicts' / 'general.json'
        )
        if general_dict_path.exists():
            try:
                general_data = load_dict(general_dict_path)
                print(f'  通用词典：{len(general_data.get("terms", {}))} 条（{general_dict_path}）')
            except Exception as e:
                print(f'  [警告] 通用词典加载失败：{e}，继续不使用通用词典。')
        else:
            print(f'  [警告] 通用词典不存在：{general_dict_path}，跳过。')

    ip_dict_path = Path(args.ip_dict) if args.ip_dict else _auto_ip_dict_path(html_path)
    ip_data = _load_ip_dict_data(ip_dict_path)
    ip_terms_count = len(ip_data.get('terms', {}))
    status = '（已有）' if ip_dict_path.exists() else '（将新建）'
    print(f'  IP 词典：{ip_terms_count} 条 {status}（{ip_dict_path}）')

    # 合并词典
    term_map: dict[str, str] = merge_dicts(general_data, ip_data)
    print(f'  合并后术语表：{len(term_map)} 条')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. 术语提取（可选）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not args.skip_term_extract:
        step('术语提取与 CLI 确认')
        all_blocks = work.body + work.tags + work.summary + work.notes + work.endnotes
        try:
            new_terms = extract_and_confirm(all_blocks, existing_terms=term_map)
        except Exception as e:
            print(f'  [警告] 术语提取失败：{e}')
            print('  继续使用现有词典翻译。')
            new_terms = {}

        if new_terms:
            _save_ip_dict(ip_dict_path, ip_data, new_terms)
            term_map.update(new_terms)
            print(f'  词典已更新，共 {len(term_map)} 条术语可用。')
        else:
            print('  无新术语加入词典。')
    else:
        print('\n[跳过] 术语提取（--skip-term-extract）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. 翻译（标签 + 摘要 + 前言 + 正文 + 尾注）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('翻译所有段落')

    # 断点续传：恢复已翻译内容
    all_blocks_for_progress = (
        work.tags + work.summary + work.notes + work.body + work.endnotes
    )
    if progress_path.exists():
        restored = load_progress(progress_path, all_blocks_for_progress)
        if restored > 0:
            print(f'  [断点续传] 已恢复 {restored} 段已完成译文')

    # 非正文区（标签、摘要、前言、尾注）——不使用进度文件，通常很短
    non_body_blocks = work.tags + work.summary + work.notes + work.endnotes
    pending_non_body = [b for b in non_body_blocks if not b.translation and b.text.strip()]
    if pending_non_body:
        print(f'  翻译非正文区（{len(pending_non_body)} 段）...')
        try:
            translate_work(pending_non_body, term_map=term_map)
        except Exception as e:
            print(f'  [警告] 非正文区翻译失败：{e}，将使用原文代替。')

    # 正文——使用进度文件支持断点续传
    if work.body:
        print(f'  翻译正文（{len(work.body)} 段）...')
        try:
            translate_work(work.body, term_map=term_map, progress_path=progress_path)
        except Exception as e:
            print(f'  [错误] 正文翻译失败：{e}')
            print(f'  已翻译内容已保存至：{progress_path}')
            print('  修复问题后重新运行，将自动从断点继续。')
            return 1

    # 词典漏译校验
    warnings = verify_terms(work.body, term_map)
    if warnings:
        print(f'\n  [漏译警告] 发现 {len(warnings)} 处术语未被正确翻译：')
        for w in warnings[:10]:
            print(f'    {w}')
        if len(warnings) > 10:
            print(f'    ...（共 {len(warnings)} 条，已只显示前 10 条）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. 润色（可选，仅正文）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not args.skip_polish:
        step('润色正文')
        try:
            polish_work(work.body, skip_polish=False)
        except Exception as e:
            print(f'  [警告] 润色失败：{e}，跳过润色使用翻译原文继续。')
    else:
        print('\n[跳过] 润色（--skip-polish）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. 输出 txt / Markdown / docx
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('输出文件（txt → 精校暂停 → Markdown → docx）')
    try:
        output_paths = write_all(work, html_path)
    except Exception as e:
        print(f'[错误] 输出失败：{e}')
        return 1

    # 清理断点续传文件
    if progress_path.exists():
        try:
            progress_path.unlink()
            print(f'  [清理] 已删除断点续传文件：{progress_path}')
        except Exception:
            pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 8. 完成摘要
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('完成')
    print()
    print('=' * 60)
    print('  ATO3 翻译完成！')
    print('=' * 60)
    print(f'  作品：{work.title}')
    print(f'  作者：{work.author}')
    print(f'  正文段落数：{total_body}')
    print(f'  使用术语：{len(term_map)} 条')
    print()
    print('  输出文件：')
    print(f'    txt  → {output_paths["txt"]}')
    print(f'    md   → {output_paths["md"]}')
    print(f'    docx → {output_paths["docx"]}')
    print('=' * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
