"""
main.py — ATO3 主流程入口

用法（CLI 模式）：
    python main.py <html_file> [选项]

用法（交互式模式）：
    python main.py          （不带任何参数，引导逐步输入）

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
        help='源语言代码（默认：en；可选 ja/ko/fr/de/es/ru 等）',
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
    parser.add_argument(
        '--docx-template', default=None, metavar='PATH',
        help='pandoc --reference-doc 模板路径（可选，用于指定 docx 字体/样式）',
    )
    return parser.parse_args(argv)


# ── 交互式输入 ────────────────────────────────────────────────────────────

def _interactive_input() -> list[str]:
    """
    引导用户逐步输入参数，返回等价的 argv 列表供 argparse 解析。
    仅在 main() 检测到无命令行参数时调用。
    """
    print()
    print('=' * 60)
    print('  ATO3 交互式启动')
    print('  （带参数运行可跳过此流程：python main.py <file> [选项]）')
    print('=' * 60)
    print()

    argv: list[str] = []

    # 1. HTML 文件路径（必填，循环直到有效）
    while True:
        try:
            raw = input('请输入 AO3 HTML 文件路径：').strip().strip('"').strip("'")
        except EOFError:
            print('\n[错误] 交互模式需要终端环境，请改用命令行参数：')
            print('  python main.py <html_file> [选项]')
            sys.exit(1)
        if not raw:
            print('  路径不能为空，请重新输入。')
            continue
        if not Path(raw).exists():
            print(f'  文件不存在：{raw}')
            print('  请检查路径后重新输入（支持粘贴带引号的路径）。')
            continue
        argv.append(raw)
        break

    # 2. 源语言（默认 en）
    print('  可选语言代码：en（英文）/ ja（日文）/ ko（韩文）/ fr（法文）/ de（德文）/ es（西班牙文）/ ru（俄文）')
    source_lang_input = input('源语言代码（回车使用默认值 en）：').strip().lower()
    if source_lang_input and source_lang_input != 'en':
        argv.extend(['--source-lang', source_lang_input])

    # 3. 是否跳过术语提取
    skip_extract = input('跳过术语提取，直接使用现有词典？[y 跳过 / 回车继续提取]: ').strip().lower()
    if skip_extract == 'y':
        argv.append('--skip-term-extract')

    # 4. 是否跳过润色
    skip_polish = input('跳过润色步骤？[y 跳过 / 回车执行润色]: ').strip().lower()
    if skip_polish == 'y':
        argv.append('--skip-polish')

    # 5. IP 词典路径（扫描 dicts/ip/ 目录供编号选择）
    ip_dir = Path(__file__).parent / 'dicts' / 'ip'
    ip_json_files = sorted(ip_dir.glob('*.json')) if ip_dir.exists() else []
    if ip_json_files:
        print('  dicts/ip/ 目录下已有以下 IP 词典：')
        for idx, f in enumerate(ip_json_files, 1):
            print(f'    [{idx}] {f.name}')
        print(f'    [0] 不选择（按输入文件名自动推断）')
        while True:
            sel = input(f'请选择 IP 词典编号（0-{len(ip_json_files)}，回车=0）：').strip()
            if sel == '' or sel == '0':
                break
            if sel.isdigit() and 1 <= int(sel) <= len(ip_json_files):
                argv.extend(['--ip-dict', str(ip_json_files[int(sel) - 1])])
                break
            print(f'  请输入 0 到 {len(ip_json_files)} 之间的数字。')
    else:
        ip_dict = input('IP 词典路径（回车自动按文件名推断）：').strip().strip('"').strip("'")
        if ip_dict:
            argv.extend(['--ip-dict', ip_dict])

    # 6. 是否禁用通用词典
    no_general = input('禁用通用词典？[y 禁用 / 回车启用]: ').strip().lower()
    if no_general == 'y':
        argv.append('--no-general-dict')

    # 7. docx 模板（自动检测默认路径）
    default_tpl = Path(__file__).parent / 'markdown-to-docx' / 'template.docx'
    if default_tpl.exists():
        print(f'  检测到默认 docx 模板：{default_tpl}')
        use_default_tpl = input('使用该模板？[回车使用 / n 跳过 / 输入其他路径]: ').strip()
        if use_default_tpl.lower() == 'n':
            pass  # 不使用任何模板
        elif use_default_tpl == '':
            argv.extend(['--docx-template', str(default_tpl)])
        else:
            custom_tpl = use_default_tpl.strip('"').strip("'")
            if Path(custom_tpl).exists():
                argv.extend(['--docx-template', custom_tpl])
            else:
                print(f'  [警告] 路径不存在：{custom_tpl}，将不使用模板。')
    else:
        docx_tpl = input('docx 模板路径（回车跳过，不使用模板）：').strip().strip('"').strip("'")
        if docx_tpl:
            argv.extend(['--docx-template', docx_tpl])

    print()
    print(f'等价命令：python main.py {" ".join(argv)}')
    print()
    return argv


# ── 主流程 ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    if argv is None and len(sys.argv) == 1:
        argv = _interactive_input()
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
            new_terms, session_terms = extract_and_confirm(all_blocks, existing_terms=term_map, source_lang=args.source_lang)
        except Exception as e:
            print(f'  [警告] 术语提取失败：{e}')
            print('  继续使用现有词典翻译。')
            new_terms = {}
            session_terms = {}

        if new_terms:
            _save_ip_dict(ip_dict_path, ip_data, new_terms)
            term_map.update(new_terms)
            print(f'  词典已更新，共 {len(term_map)} 条术语可用。')
        else:
            print('  无新术语加入词典。')

        if session_terms:
            term_map.update(session_terms)
            print(f'  临时术语表：{len(session_terms)} 条（仅本次翻译有效，不写入词典）。')
    else:
        session_terms = {}
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
            translate_work(pending_non_body, term_map=term_map, source_lang=args.source_lang)
        except Exception as e:
            print(f'  [警告] 非正文区翻译失败：{e}，将使用原文代替。')

    # 正文——使用进度文件支持断点续传
    if work.body:
        print(f'  翻译正文（{len(work.body)} 段）...')
        try:
            translate_work(work.body, term_map=term_map, progress_path=progress_path, source_lang=args.source_lang)
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
            polish_work(work.body, skip_polish=False, source_lang=args.source_lang, chapters=work.chapters)
        except Exception as e:
            print(f'  [警告] 润色失败：{e}，跳过润色使用翻译原文继续。')
    else:
        print('\n[跳过] 润色（--skip-polish）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. 输出 txt / Markdown / docx
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('输出文件（txt → 精校暂停 → Markdown → 检视暂停 → docx）')
    reference_doc = Path(args.docx_template) if args.docx_template else None
    try:
        output_paths = write_all(work, html_path, reference_doc=reference_doc)
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
