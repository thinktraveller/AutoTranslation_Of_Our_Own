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
    --profile NAME          使用指定的模型方案（fast/balanced/quality 或自定义方案名）
    --output-dir PATH       指定输出文件夹路径（默认：HTML 文件同级目录下创建同名子文件夹）

断点续传：
    任务执行期间，在三处用户介入节点（术语确认后、txt 精校后、Markdown 检视后）可输入
    [s] 保存进度并退出。下次启动时，程序会列出未完成任务并提供恢复选项。
    进度文件存储在 logs/{文件名}_{时间戳}/ 子目录下。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

# ── Windows UTF-8 模式（必须在其他导入前设置）──────────────────────────────
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONUTF8', '1')
    if hasattr(sys.stdout, 'reconfigure'):
        cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        cast(io.TextIOWrapper, sys.stderr).reconfigure(encoding='utf-8', errors='replace')


from src.html_parser import parse_ao3_html
from src.dict_manager import load_dict, save_dict, merge_dicts
from src.term_extractor import extract_and_confirm
from src.translator import translate_work, verify_terms, save_progress, load_progress
from src.polisher import polish_work
from src.output_writer import (
    write_txt, pause_for_proofread, write_markdown, pause_before_docx,
    write_docx, get_output_paths, _safe_stem,
)
from src.llm_config import get_profile_config


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


# ── 日志文件夹与任务状态管理 ──────────────────────────────────────────────

_LOGS_ROOT = Path("logs")
_TASK_STATE_FILENAME = "task_state.json"
_PROGRESS_FILENAME = "progress.json"

# task_state.json 中 breakpoint 字段的合法值
_BP_AFTER_TERM_CONFIRM = "after_term_confirm"
_BP_AFTER_TXT_POLISH = "after_txt_polish"
_BP_AFTER_MD_REVIEW = "after_md_review"

# task_state.json 版本号（供未来格式升级使用）
_TASK_STATE_VERSION = 1


def _create_task_log_dir(html_path: str | Path) -> Path:
    """
    在 logs/ 下创建本次任务的子日志文件夹，命名规则：{安全词干}_{时间戳}。
    返回创建好的 Path 对象。
    """
    stem = _safe_stem(Path(html_path).stem)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = _LOGS_ROOT / f"{stem}_{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _save_task_state(state: dict, log_dir: Path) -> None:
    """
    原子写入 task_state.json（先写 .tmp 再重命名），防止中断时文件损坏。
    """
    state_path = log_dir / _TASK_STATE_FILENAME
    tmp_path = state_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(state_path)
    except Exception as e:
        print(f"  [断点] task_state.json 写入失败：{e}")


def _build_initial_task_state(html_path: str | Path, args: argparse.Namespace) -> dict:
    """根据当前参数构造初始 task_state 字典（breakpoint=null 表示进行中）。"""
    p = Path(html_path)
    return {
        "version": _TASK_STATE_VERSION,
        "html_path": str(p),
        "html_stem": _safe_stem(p.stem),
        "started_at": datetime.now().isoformat(),
        "interrupted_at": None,
        "breakpoint": None,
        "args": {
            "profile": args.profile,
            "skip_polish": args.skip_polish,
            "skip_term_extract": args.skip_term_extract,
            "source_lang": args.source_lang,
            "output_dir": args.output_dir,
            "ip_dict": args.ip_dict,
            "no_general_dict": args.no_general_dict,
            "general_dict": args.general_dict,
            "docx_template": args.docx_template,
        },
        "cache": {},
    }


def _breakpoint_prompt(label: str, breakpoint_key: str,
                       task_state: dict, log_dir: Path) -> bool:
    """
    在用户介入节点询问是否继续。
    返回 True 表示继续执行，False 表示用户选择保存并中断。
    """
    print(f"\n[断点] {label}")
    print("  [Enter] 继续执行")
    print("  [s]     保存进度并退出（下次启动可从此处恢复）")
    try:
        choice = input("请选择：").strip().lower()
    except EOFError:
        choice = ""
    if choice == "s":
        task_state["breakpoint"] = breakpoint_key
        task_state["interrupted_at"] = datetime.now().isoformat()
        _save_task_state(task_state, log_dir)
        print(f"  进度已保存至 {log_dir / _TASK_STATE_FILENAME}")
        print("  下次启动脚本时可选择恢复此任务。")
        return False
    return True


def _find_incomplete_tasks() -> list[dict]:
    """
    扫描 logs/ 目录，返回所有 breakpoint 不为 null 的未完成任务列表（最新在前）。
    """
    if not _LOGS_ROOT.exists():
        return []
    incomplete: list[dict] = []
    for sub in sorted(_LOGS_ROOT.iterdir(), reverse=True):
        if not sub.is_dir():
            continue
        state_file = sub / _TASK_STATE_FILENAME
        if not state_file.exists():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(state, dict) and state.get("breakpoint") is not None:
            incomplete.append({**state, "_log_dir": str(sub)})
    return incomplete


def _prompt_resume(incomplete: list[dict]) -> dict | None:
    """
    列出未完成任务，让用户选择：数字恢复、d<序号>删除、回车忽略。
    返回要恢复的 state dict，或 None（忽略/删除后不恢复）。
    """
    print("\n发现以下未完成的翻译任务：\n")
    _BP_CN = {
        _BP_AFTER_TERM_CONFIRM: "术语确认后",
        _BP_AFTER_TXT_POLISH:   "txt 精校后",
        _BP_AFTER_MD_REVIEW:    "Markdown 检视后",
    }
    for i, s in enumerate(incomplete, 1):
        bp_cn = _BP_CN.get(s.get("breakpoint", ""), s.get("breakpoint", ""))
        print(f"  [{i}] {s.get('html_stem', '?')}  "
              f"中断：{s.get('interrupted_at', '?')}  断点：{bp_cn}")
    print("  [d<序号>] 删除对应任务记录（如 d1）")
    print("  [Enter]   忽略，开始新任务")
    try:
        choice = input("\n请选择：").strip().lower()
    except EOFError:
        return None
    if not choice:
        return None
    if choice.startswith("d") and choice[1:].isdigit():
        idx = int(choice[1:]) - 1
        if 0 <= idx < len(incomplete):
            log_dir = incomplete[idx]["_log_dir"]
            shutil.rmtree(log_dir, ignore_errors=True)
            print(f"  已删除：{log_dir}")
        return None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(incomplete):
            return incomplete[idx]
    return None


# ── 统一断点续传检查点 ─────────────────────────────────────────────────────

# 检查点文件名（固定，不随输入文件名变化）
_CHECKPOINT_FILENAME = ".translation_checkpoint.json"

# 阶段标识（按执行顺序）
_PHASE_NON_BODY = "non_body"      # 标签/摘要/前言/尾注翻译
_PHASE_BODY = "body"              # 正文翻译
_PHASE_POLISH = "polish"          # 润色（完成标记，无段落数据）


def _checkpoint_path(html_path: Path, log_dir: Path | None = None) -> Path:
    """
    返回检查点文件（progress.json）的绝对路径。
    若提供 log_dir，将文件放在子日志文件夹内；否则回退到 HTML 同目录（兼容旧检查点）。
    """
    if log_dir is not None:
        return log_dir / _PROGRESS_FILENAME
    return html_path.parent / _CHECKPOINT_FILENAME


def _load_checkpoint(ckpt_path: Path) -> dict:
    """
    加载检查点文件，返回 dict。
    结构：
      {
        "source_file": str,          # 输入 HTML 文件名（用于校验）
        "phases": {
          "non_body": {"done": bool, "translations": {block_id: text}},
          "body":     {"done": bool, "translations": {block_id: text}},
          "polish":   {"done": bool},
        }
      }
    若文件不存在或解析失败，返回空结构。
    """
    if not ckpt_path.exists():
        return {}
    try:
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_checkpoint(ckpt_path: Path, source_file: str, phases: dict) -> None:
    """
    原子写入检查点文件。
    phases 结构同 _load_checkpoint 返回值的 "phases" 字段。
    """
    data = {"source_file": source_file, "phases": phases}
    tmp = ckpt_path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ckpt_path)
    except Exception as e:
        print(f"  [断点续传] 检查点写入失败：{e}")


def _blocks_to_translations(blocks: list) -> dict:
    """将已有译文的 block 列表转为 {block_id: translation} 字典。"""
    return {b.block_id: b.translation for b in blocks if b.translation}


def _restore_from_translations(translations: dict, blocks: list) -> int:
    """将 {block_id: translation} 回填到 blocks，返回恢复数量。"""
    id_map = {b.block_id: b for b in blocks}
    count = 0
    for bid, tr in translations.items():
        if bid in id_map and tr:
            id_map[bid].translation = tr
            count += 1
    return count


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
    parser.add_argument(
        '--profile', default=None, metavar='NAME',
        help='使用指定的模型方案（如 fast / balanced / quality）。'
             '未指定时使用 config.json 中的 default_profile，或旧版 agents 字段。',
    )
    parser.add_argument(
        '--output-dir', default=None, metavar='PATH',
        help='指定输出文件夹路径。默认在 HTML 文件同级目录下创建同名子文件夹。',
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

    # 2. 模型方案选择
    print()
    # 动态读取 config.json，生成实际可用方案列表（过滤 deleted_profiles）
    _builtin_names = ["fast", "balanced", "quality"]
    _builtin_desc = {
        "fast":     "全程 DeepSeek（速度快、成本低）",
        "balanced": "DeepSeek 翻译 + GPT-4o-mini 润色（推荐）",
        "quality":  "全程 OpenAI GPT-4o（质量最优）",
    }
    _available_profiles: list[str] = []
    try:
        from src.llm_config import load_config as _load_cfg
        _cfg = _load_cfg()
        _deleted = set(_cfg.get("deleted_profiles", []))
        # 未被删除的内置方案
        for _bn in _builtin_names:
            if _bn not in _deleted:
                _available_profiles.append(_bn)
        # 用户自定义方案（不在内置名列表中）
        for _k in _cfg.get("profiles", {}):
            if _k not in _builtin_names:
                _available_profiles.append(_k)
    except Exception:
        # config.json 不可读时，退回显示全部内置方案
        _available_profiles = list(_builtin_names)

    print('可用模型方案：')
    _profile_map: dict[str, str] = {}
    for _i, _pname in enumerate(_available_profiles, 1):
        _desc = _builtin_desc.get(_pname, "自定义方案")
        print(f'  [{_i}] {_pname} - {_desc}')
        _profile_map[str(_i)] = _pname
    _total_choices = len(_available_profiles)
    print(f'  [{_total_choices + 1}] 使用配置文件中的 default_profile（或旧版 agents 字段）')
    print()

    while True:
        _sel = input(f'请选择方案 [1-{_total_choices + 1}，默认 {_total_choices + 1}]：').strip()
        if _sel == '' or _sel == str(_total_choices + 1):
            break  # 不追加 --profile，由配置文件决定
        if _sel in _profile_map:
            argv.extend(['--profile', _profile_map[_sel]])
            break
        print(f'  请输入 1 到 {_total_choices + 1} 之间的数字。')

    # 3. 源语言（默认 en）
    print('  可选语言代码：en（英文）/ ja（日文）/ ko（韩文）/ fr（法文）/ de（德文）/ es（西班牙文）/ ru（俄文）')
    source_lang_input = input('源语言代码（回车使用默认值 en）：').strip().lower()
    if source_lang_input and source_lang_input != 'en':
        argv.extend(['--source-lang', source_lang_input])

    # 4. 是否跳过术语提取
    skip_extract = input('跳过术语提取，直接使用现有词典？[y 跳过 / 回车继续提取]: ').strip().lower()
    if skip_extract == 'y':
        argv.append('--skip-term-extract')

    # 5. 是否跳过润色
    skip_polish = input('跳过润色步骤？[y 跳过 / 回车执行润色]: ').strip().lower()
    if skip_polish == 'y':
        argv.append('--skip-polish')

    # 6. IP 词典路径（扫描 dicts/ip/ 目录供编号选择）
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

    # 7. 是否禁用通用词典
    no_general = input('禁用通用词典？[y 禁用 / 回车启用]: ').strip().lower()
    if no_general == 'y':
        argv.append('--no-general-dict')

    # 8. docx 模板（自动检测默认路径）
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

    # 9. 输出目录（可选，默认使用 HTML 同级同名子文件夹）
    out_dir = input('输出目录（回车使用默认：HTML 同级同名文件夹）：').strip().strip('"').strip("'")
    if out_dir:
        argv.extend(['--output-dir', out_dir])

    print()
    print(f'等价命令：python main.py {" ".join(argv)}')
    print()
    return argv


# ── 主流程 ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    # ── 启动时扫描未完成任务（仅在无参数/交互模式时扫描）──────────────────
    _resume_state: dict | None = None
    _resume_log_dir: Path | None = None

    if argv is None and len(sys.argv) == 1:
        # 先扫描，再进入交互式输入
        _incomplete = _find_incomplete_tasks()
        if _incomplete:
            _resume_state = _prompt_resume(_incomplete)
            if _resume_state is not None:
                # 从保存的 args 重建 argv，跳过交互模式
                _saved_args = _resume_state.get("args", {})
                _resume_log_dir = Path(_resume_state["_log_dir"])
                _rebuild_argv: list[str] = [_resume_state["html_path"]]
                if _saved_args.get("profile"):
                    _rebuild_argv.extend(["--profile", _saved_args["profile"]])
                if _saved_args.get("skip_polish"):
                    _rebuild_argv.append("--skip-polish")
                if _saved_args.get("skip_term_extract"):
                    _rebuild_argv.append("--skip-term-extract")
                if _saved_args.get("source_lang") and _saved_args["source_lang"] != "en":
                    _rebuild_argv.extend(["--source-lang", _saved_args["source_lang"]])
                if _saved_args.get("output_dir"):
                    _rebuild_argv.extend(["--output-dir", _saved_args["output_dir"]])
                if _saved_args.get("ip_dict"):
                    _rebuild_argv.extend(["--ip-dict", _saved_args["ip_dict"]])
                if _saved_args.get("no_general_dict"):
                    _rebuild_argv.append("--no-general-dict")
                if _saved_args.get("general_dict"):
                    _rebuild_argv.extend(["--general-dict", _saved_args["general_dict"]])
                if _saved_args.get("docx_template"):
                    _rebuild_argv.extend(["--docx-template", _saved_args["docx_template"]])
                argv = _rebuild_argv
                print(f"\n[恢复] 从断点恢复任务：{_resume_state.get('html_stem', '?')}")
                print(f"  断点位置：{_resume_state.get('breakpoint')}")
                print(f"  日志目录：{_resume_log_dir}")
            else:
                # 用户选择忽略或删除，正常进入交互模式
                argv = _interactive_input()
        else:
            argv = _interactive_input()

    args = _parse_args(argv)

    # ── 加载模型方案配置（四级优先级：--profile > default_profile > agents > 硬编码）──
    try:
        profile_cfg = get_profile_config(args.profile)
        _profile_name = args.profile or 'default_profile / agents'
        print(f'  [方案] 使用模型方案：{_profile_name}')
    except Exception as e:
        print(f'  [警告] 加载模型方案失败：{e}，将使用 config.json 的 agents 字段兜底。')
        profile_cfg = None

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

    # ── 创建（或恢复）子日志文件夹 ─────────────────────────────────────────
    if _resume_log_dir is not None and _resume_log_dir.exists():
        task_log_dir = _resume_log_dir
        print(f'  [日志] 使用已有日志目录：{task_log_dir}')
    else:
        task_log_dir = _create_task_log_dir(html_path)
        print(f'  [日志] 任务日志目录：{task_log_dir}')

    # ── 初始化任务状态（task_state.json）─────────────────────────────────
    if _resume_state is not None:
        # 恢复：沿用已有 state，清空断点标记，更新启动时间
        task_state = dict(_resume_state)
        task_state.pop("_log_dir", None)
        task_state["breakpoint"] = None
        task_state["interrupted_at"] = None
        task_state["started_at"] = datetime.now().isoformat()
    else:
        task_state = _build_initial_task_state(html_path, args)

    _save_task_state(task_state, task_log_dir)

    # ── 统一断点续传检查点（四阶段共用，迁移到子日志文件夹）──────────────
    ckpt_path = _checkpoint_path(html_path, log_dir=task_log_dir)
    ckpt = _load_checkpoint(ckpt_path)
    source_key = html_path.name  # 用于校验检查点是否匹配当前文件

    # 若检查点属于另一个文件，丢弃
    if ckpt and ckpt.get("source_file") != source_key:
        print(f'  [断点续传] 检查点属于不同文件（{ckpt.get("source_file")}），已忽略。')
        ckpt = {}

    phases: dict = ckpt.get("phases", {})
    if phases:
        print(f'  [断点续传] 检测到已有检查点：{ckpt_path}')

    # ── Ctrl+C 捕获（保存当前进度后优雅退出）──────────────────────────────
    # _work / _term_map 在主流程中赋值后由信号处理器访问
    _sigint_ctx: dict = {"work": None, "ckpt_path": ckpt_path, "source_key": source_key, "phases": phases}

    def _sigint_handler(signum, frame):  # noqa: ANN001
        print()
        print('\n[中断] 检测到 Ctrl+C，正在保存进度...')
        w = _sigint_ctx.get("work")
        ph = _sigint_ctx.get("phases", {})
        if w is not None:
            # 保存当前已翻译的段落
            nb = w.tags + w.summary + w.notes + w.endnotes
            b = w.body
            if _PHASE_NON_BODY not in ph:
                ph[_PHASE_NON_BODY] = {}
            ph[_PHASE_NON_BODY]["translations"] = _blocks_to_translations(nb)
            ph[_PHASE_NON_BODY]["done"] = all(
                bl.translation for bl in nb if bl.text.strip()
            )
            if _PHASE_BODY not in ph:
                ph[_PHASE_BODY] = {}
            ph[_PHASE_BODY]["translations"] = _blocks_to_translations(b)
            ph[_PHASE_BODY]["done"] = all(
                bl.translation for bl in b if bl.text.strip()
            )
            _save_checkpoint(_sigint_ctx["ckpt_path"], _sigint_ctx["source_key"], ph)
            print(f'  进度已保存至：{_sigint_ctx["ckpt_path"]}')
        print()
        print('  续翻说明：直接重新运行相同命令，将自动从断点继续：')
        print(f'    python main.py {args.html_file}' + (
            f' --skip-term-extract' if args.skip_term_extract else ''
        ) + (
            f' --skip-polish' if args.skip_polish else ''
        ))
        sys.exit(130)

    # 注册信号（Windows 上 SIGINT 可用；SIGTERM 在部分 Windows 版本受限）
    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except (OSError, ValueError):
        pass  # 非主线程或不支持时静默忽略

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. 解析 HTML
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('解析 HTML')
    try:
        work = parse_ao3_html(str(html_path))
    except Exception as e:
        print(f'[错误] HTML 解析失败：{e}')
        return 1

    # 让信号处理器可以访问 work 对象
    _sigint_ctx["work"] = work

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
            new_terms, session_terms = extract_and_confirm(
                all_blocks, existing_terms=term_map,
                source_lang=args.source_lang, profile=profile_cfg,
            )
        except KeyboardInterrupt:
            raise  # 交给上层信号处理器
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

        # ── 断点 1：术语确认后 ────────────────────────────────────────────
        # 仅在不是从该断点恢复时显示（避免恢复时重复询问）
        _resuming_bp = _resume_state.get("breakpoint") if _resume_state else None
        if _resuming_bp != _BP_AFTER_TERM_CONFIRM:
            task_state["cache"]["terms_log_path"] = str(task_log_dir / "terms_extracted.json")
            _save_task_state(task_state, task_log_dir)
            if not _breakpoint_prompt(
                "术语确认完成。请检查 IP 词典，按 Enter 继续翻译...",
                _BP_AFTER_TERM_CONFIRM,
                task_state,
                task_log_dir,
            ):
                return 0
    else:
        session_terms = {}
        print('\n[跳过] 术语提取（--skip-term-extract）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. 翻译（标签 + 摘要 + 前言 + 正文 + 尾注）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('翻译所有段落')

    non_body_blocks = work.tags + work.summary + work.notes + work.endnotes

    # ── 从检查点恢复非正文区 ───────────────────────────────────────────────
    non_body_phase = phases.get(_PHASE_NON_BODY, {})
    if non_body_phase.get("translations"):
        restored_nb = _restore_from_translations(non_body_phase["translations"], non_body_blocks)
        if restored_nb > 0:
            print(f'  [断点续传] 非正文区已恢复 {restored_nb} 段译文')

    # ── 从检查点恢复正文 ───────────────────────────────────────────────────
    body_phase = phases.get(_PHASE_BODY, {})
    if body_phase.get("translations"):
        restored_body = _restore_from_translations(body_phase["translations"], work.body)
        if restored_body > 0:
            print(f'  [断点续传] 正文已恢复 {restored_body} 段译文')

    # ── 翻译非正文区（标签、摘要、前言、尾注）────────────────────────────
    if non_body_phase.get("done"):
        print('  [跳过] 非正文区已完成（来自检查点）')
    else:
        pending_non_body = [b for b in non_body_blocks if not b.translation and b.text.strip()]
        if pending_non_body:
            print(f'  翻译非正文区（{len(pending_non_body)} 段）...')
            try:
                translate_work(
                    pending_non_body, term_map=term_map,
                    source_lang=args.source_lang, profile=profile_cfg,
                )
            except KeyboardInterrupt:
                raise  # 交给信号处理器
            except Exception as e:
                print(f'  [警告] 非正文区翻译失败：{e}，将使用原文代替。')
        # 保存非正文区进度到检查点
        phases[_PHASE_NON_BODY] = {
            "done": all(b.translation for b in non_body_blocks if b.text.strip()),
            "translations": _blocks_to_translations(non_body_blocks),
        }
        _save_checkpoint(ckpt_path, source_key, phases)

    # ── 翻译正文（支持断点续传）───────────────────────────────────────────
    if body_phase.get("done"):
        print('  [跳过] 正文翻译已完成（来自检查点）')
    elif work.body:
        print(f'  翻译正文（{len(work.body)} 段）...')
        try:
            translate_work(
                work.body, term_map=term_map,
                source_lang=args.source_lang, profile=profile_cfg,
            )
        except KeyboardInterrupt:
            raise  # 交给信号处理器
        except Exception as e:
            # 保存当前进度到检查点，再退出
            phases[_PHASE_BODY] = {
                "done": False,
                "translations": _blocks_to_translations(work.body),
            }
            _save_checkpoint(ckpt_path, source_key, phases)
            print(f'  [错误] 正文翻译失败：{e}')
            print(f'  已翻译内容已保存至：{ckpt_path}')
            print('  修复问题后重新运行，将自动从断点继续。')
            return 1
        # 翻译完成，更新检查点
        phases[_PHASE_BODY] = {
            "done": True,
            "translations": _blocks_to_translations(work.body),
        }
        _save_checkpoint(ckpt_path, source_key, phases)

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
        polish_phase = phases.get(_PHASE_POLISH, {})
        if polish_phase.get("done"):
            print('\n[跳过] 润色已完成（来自检查点）')
        else:
            step('润色正文')
            try:
                polish_work(
                    work.body, skip_polish=False,
                    source_lang=args.source_lang, chapters=work.chapters,
                    profile=profile_cfg,
                )
            except KeyboardInterrupt:
                raise  # 交给信号处理器
            except Exception as e:
                print(f'  [警告] 润色失败：{e}，跳过润色使用翻译原文继续。')
            # 标记润色已完成
            phases[_PHASE_POLISH] = {"done": True}
            _save_checkpoint(ckpt_path, source_key, phases)
    else:
        print('\n[跳过] 润色（--skip-polish）')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. 输出 txt / Markdown / docx（逐步执行，含两处断点）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    step('输出文件（txt → 精校断点 → Markdown → 检视断点 → docx）')
    reference_doc = Path(args.docx_template) if args.docx_template else None
    output_dir = args.output_dir if args.output_dir else None
    output_paths = get_output_paths(html_path, output_dir=output_dir)
    task_state["cache"]["output_dir"] = str(output_paths["txt"].parent)
    _save_task_state(task_state, task_log_dir)

    _resuming_bp = _resume_state.get("breakpoint") if _resume_state else None

    # ── 7-A: 写 txt ───────────────────────────────────────────────────────
    # 从 after_txt_polish 或 after_md_review 断点恢复时，txt 已存在，跳过
    _skip_txt = (
        _resuming_bp in (_BP_AFTER_TXT_POLISH, _BP_AFTER_MD_REVIEW)
        and output_paths["txt"].exists()
    )
    if not _skip_txt:
        try:
            write_txt(work, output_paths["txt"])
        except Exception as e:
            print(f'[错误] txt 输出失败：{e}')
            return 1
    else:
        print(f'  [跳过] txt 已存在（来自断点恢复）：{output_paths["txt"]}')

    # ── 7-B: 精校暂停 + 断点 2（after_txt_polish）────────────────────────
    # after_txt_polish：用户已精校 txt，直接读取精校内容跳过暂停
    # after_md_review：md 已生成，跳过精校和 md 生成
    _skip_proofread = (
        _resuming_bp in (_BP_AFTER_TXT_POLISH, _BP_AFTER_MD_REVIEW)
        and output_paths["txt"].exists()
    )
    if not _skip_proofread:
        proofread_paragraphs = pause_for_proofread(output_paths["txt"])
        body_count = sum(1 for b in work.body if b.translation)
        if len(proofread_paragraphs) != body_count:
            print(
                f'[警告] 精校后段落数（{len(proofread_paragraphs)}）'
                f'与原始正文段落数（{body_count}）不一致。'
            )
            try:
                cont = input('是否继续？(y/n): ').strip().lower()
            except EOFError:
                cont = 'y'
            if cont != 'y':
                print('已取消。txt 文件保留，md 和 docx 未生成。')
                return 0
        for i, block in enumerate(work.body):
            if i < len(proofread_paragraphs):
                block.translation = proofread_paragraphs[i]

        # 断点 2
        if not _breakpoint_prompt(
            "txt 已生成，请精校正文后按 Enter 继续生成 Markdown...",
            _BP_AFTER_TXT_POLISH,
            task_state,
            task_log_dir,
        ):
            return 0
    else:
        # 从断点恢复：读取已精校的 txt 内容，回填 work.body
        _txt = output_paths["txt"].read_text(encoding="utf-8")
        proofread_paragraphs = [p.strip() for p in _txt.split("\n\n") if p.strip()]
        for i, block in enumerate(work.body):
            if i < len(proofread_paragraphs):
                block.translation = proofread_paragraphs[i]
        print(f'  [恢复] 已读取精校 txt（{len(proofread_paragraphs)} 段）')

    # ── 7-C: 写 Markdown ──────────────────────────────────────────────────
    _skip_md = _resuming_bp == _BP_AFTER_MD_REVIEW and output_paths["md"].exists()
    if not _skip_md:
        try:
            write_markdown(work, output_paths["md"])
        except Exception as e:
            print(f'[错误] Markdown 输出失败：{e}')
            return 1
    else:
        print(f'  [跳过] Markdown 已存在（来自断点恢复）：{output_paths["md"]}')

    # 断点 3（after_md_review）
    if not _breakpoint_prompt(
        "Markdown 已生成，请检视格式后按 Enter 继续生成 docx...",
        _BP_AFTER_MD_REVIEW,
        task_state,
        task_log_dir,
    ):
        return 0

    # ── 7-D: 写 docx ──────────────────────────────────────────────────────
    try:
        write_docx(output_paths["md"], output_paths["docx"], reference_doc=reference_doc)
    except Exception as e:
        print(f'[错误] docx 输出失败：{e}')
        # docx 失败不算致命，继续输出完成摘要

    print('\n[完成] 三种格式已全部生成：')
    print(f'  txt  → {output_paths["txt"]}')
    print(f'  md   → {output_paths["md"]}')
    print(f'  docx → {output_paths["docx"]}')

    # ── 清理检查点文件（翻译全部完成）────────────────────────────────────
    if ckpt_path.exists():
        try:
            ckpt_path.unlink()
            print(f'  [清理] 已删除断点续传检查点：{ckpt_path}')
        except Exception:
            pass

    # ── 标记任务完成（breakpoint=null）────────────────────────────────────
    task_state["breakpoint"] = None
    task_state["interrupted_at"] = None
    _save_task_state(task_state, task_log_dir)

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
