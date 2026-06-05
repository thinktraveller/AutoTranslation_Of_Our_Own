"""
dict_manager.py — 词典管理模块

提供两类接口：
1. 程序内调用 API：load_dict / save_dict / merge_dicts
2. 独立 CLI 词典编辑器：python dict_manager.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

DICTS_DIR = Path(__file__).parent.parent / "dicts"
IP_DIR = DICTS_DIR / "ip"
GENERAL_DICT = DICTS_DIR / "general.json"

# ──────────────────────────────────────────────
# 程序内调用 API
# ──────────────────────────────────────────────


def load_dict(path: str | Path) -> dict[str, Any]:
    """
    从 JSON 文件加载词典数据。

    返回完整的词典结构（含 meta 和 terms）。
    若文件不存在，抛出 FileNotFoundError。
    若 JSON 格式错误，抛出 ValueError 并附带原始错误信息。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"词典文件不存在：{path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"词典文件 JSON 格式错误：{path}\n{e}") from e

    # 兼容缺少 meta 或 terms 的旧格式
    if "terms" not in data:
        data["terms"] = {}
    if "meta" not in data:
        data["meta"] = {
            "name": path.stem,
            "version": "1.0",
            "updated": str(date.today()),
        }
    return data


def save_dict(path: str | Path, data: dict[str, Any]) -> None:
    """
    将词典数据安全写入 JSON 文件（先写临时文件再原子替换）。

    自动更新 meta.updated 为今日日期。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 更新修改日期
    if "meta" not in data:
        data["meta"] = {}
    data["meta"]["updated"] = str(date.today())

    # 写入同目录临时文件，再原子替换，防止写入中途崩溃损坏词典
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Windows 上 os.replace 是原子操作（同驱动器内）
        os.replace(tmp_path, path)
    except Exception:
        # 确保临时文件被清理
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def merge_dicts(
    general: dict[str, Any],
    ip: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    合并通用词典与 IP 词典，返回 {原文: 译文} 映射。

    合并规则：IP 词典优先级高于通用词典（同 key 时 IP 覆盖 general）。
    传入完整词典结构（load_dict 返回值），或仅含 terms 的字典均可。
    """

    def _get_terms(d: dict[str, Any]) -> dict[str, str]:
        return d.get("terms", d) if isinstance(d, dict) else {}

    result: dict[str, str] = {}
    result.update(_get_terms(general))
    if ip:
        result.update(_get_terms(ip))
    return result


def list_dicts() -> list[Path]:
    """返回所有可用词典文件路径（通用 + IP 子目录）。"""
    paths: list[Path] = []
    if GENERAL_DICT.exists():
        paths.append(GENERAL_DICT)
    if IP_DIR.exists():
        paths.extend(sorted(IP_DIR.glob("*.json")))
    return paths


def create_ip_dict(name: str, display_name: str | None = None) -> Path:
    """
    在 dicts/ip/ 下创建新的 IP 词典文件。

    name        : 文件名（不含 .json），如 "harry_potter"
    display_name: 词典显示名称，默认与 name 相同
    返回新建文件路径。
    若文件已存在，抛出 FileExistsError。
    """
    IP_DIR.mkdir(parents=True, exist_ok=True)
    path = IP_DIR / f"{name}.json"
    if path.exists():
        raise FileExistsError(f"IP 词典已存在：{path}")
    data: dict[str, Any] = {
        "meta": {
            "name": display_name or name,
            "version": "1.0",
            "updated": str(date.today()),
        },
        "terms": {},
    }
    save_dict(path, data)
    return path


# ──────────────────────────────────────────────
# CLI 编辑器辅助函数
# ──────────────────────────────────────────────


def _prompt(msg: str, default: str = "") -> str:
    """带默认值的输入提示。"""
    suffix = f" [{default}]" if default else ""
    val = input(f"{msg}{suffix}: ").strip()
    return val if val else default


def _pause() -> None:
    input("\n按回车键继续...")


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_header(title: str) -> None:
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)


# ──────────────────────────────────────────────
# CLI 菜单：词典列表 & 选择
# ──────────────────────────────────────────────


def _show_dict_list() -> list[Path]:
    """打印所有词典，返回路径列表（供用户按编号选择）。"""
    paths = list_dicts()
    if not paths:
        print("  （暂无词典文件）")
        return paths
    for i, p in enumerate(paths, 1):
        try:
            d = load_dict(p)
            name = d["meta"].get("name", p.stem)
            count = len(d["terms"])
            rel = p.relative_to(Path(__file__).parent.parent)
        except Exception:
            name = p.stem
            count = "?"
            rel = p
        print(f"  {i}. {name}  ({count} 条)  [{rel}]")
    return paths


def _select_dict(prompt_text: str = "请选择词典编号") -> tuple[Path, dict] | None:
    """让用户从列表中选择一个词典，返回 (path, data) 或 None（取消）。"""
    paths = _show_dict_list()
    if not paths:
        return None
    raw = _prompt(f"\n{prompt_text}（回车取消）")
    if not raw:
        return None
    try:
        idx = int(raw) - 1
        if not 0 <= idx < len(paths):
            raise ValueError
    except ValueError:
        print("  输入无效。")
        return None
    path = paths[idx]
    data = load_dict(path)
    return path, data


# ──────────────────────────────────────────────
# CLI 子菜单：词典内部操作
# ──────────────────────────────────────────────


def _menu_view_terms(path: Path, data: dict) -> None:
    """查看词典所有词条。"""
    terms = data["terms"]
    name = data["meta"].get("name", path.stem)
    _print_header(f"词典：{name}  （共 {len(terms)} 条）")
    if not terms:
        print("  （暂无词条）")
    else:
        for i, (src, tgt) in enumerate(terms.items(), 1):
            print(f"  {i:>4}. {src}  →  {tgt}")
    _pause()


def _menu_add_term(path: Path, data: dict) -> None:
    """添加单条词条。"""
    _print_header("添加词条")
    src = _prompt("原文")
    if not src:
        print("  已取消。")
        return
    if src in data["terms"]:
        print(f"  词条已存在：{src} → {data['terms'][src]}")
        overwrite = _prompt("是否覆盖？(y/n)", "n").lower()
        if overwrite != "y":
            print("  已取消。")
            return
    tgt = _prompt("译文（中文）")
    if not tgt:
        print("  译文不能为空，已取消。")
        return
    data["terms"][src] = tgt
    save_dict(path, data)
    print(f"  已添加：{src} → {tgt}")
    _pause()


def _menu_delete_term(path: Path, data: dict) -> None:
    """
    删除词条。支持两种输入方式：
    - 输入纯数字：按序号定位（序号与「查看词条」显示的编号一致）
    - 输入文本：按原文精确匹配（原有逻辑，向下兼容）
    """
    _print_header("删除词条")
    terms = data["terms"]
    if not terms:
        print("  词典为空，无可删除词条。")
        _pause()
        return

    # 展示词条列表（带序号，与查看界面保持一致）
    term_keys = list(terms.keys())
    print(f"  共 {len(term_keys)} 条词条：\n")
    for i, k in enumerate(term_keys, 1):
        print(f"  {i:>4}. {k}  →  {terms[k]}")

    raw = _prompt("\n请输入要删除的词条序号或原文（回车取消）")
    if not raw:
        print("  已取消。")
        return

    # 判断是否为纯数字序号
    src: str | None = None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(term_keys):
            src = term_keys[idx]
        else:
            print(f"  序号 {raw} 超出范围（1-{len(term_keys)}）。")
            _pause()
            return
    else:
        # 文本精确匹配（原有逻辑）
        if raw in terms:
            src = raw
        else:
            print(f"  未找到词条：{raw}")
            _pause()
            return

    confirm = _prompt(
        f"  确认删除「{src} → {terms[src]}」？(y/n)", "n"
    ).lower()
    if confirm != "y":
        print("  已取消。")
        return
    del terms[src]
    save_dict(path, data)
    print(f"  已删除：{src}")
    _pause()


def _menu_migrate_terms(src_path: Path, src_data: dict) -> None:
    """
    批量迁移：将当前词典的词条复制或移动到另一个词典。
    """
    _print_header("批量迁移词条")
    src_terms = src_data["terms"]
    if not src_terms:
        print("  当前词典为空，无可迁移词条。")
        _pause()
        return

    print(f"\n  源词典：{src_data['meta'].get('name', src_path.stem)}  （{len(src_terms)} 条）")
    print("\n  请选择目标词典：")
    result = _select_dict("目标词典编号")
    if result is None:
        print("  已取消。")
        return
    dst_path, dst_data = result

    if dst_path == src_path:
        print("  目标词典与源词典相同，已取消。")
        return

    action = _prompt("操作：复制(c) 还是 移动(m)？", "c").lower()
    if action not in ("c", "m"):
        print("  无效操作，已取消。")
        return

    # 检查冲突
    conflicts = [k for k in src_terms if k in dst_data["terms"]]
    if conflicts:
        print(f"\n  目标词典中已存在 {len(conflicts)} 条同名词条：")
        for k in conflicts[:10]:
            print(f"    {k}  →  目标：{dst_data['terms'][k]}  /  源：{src_terms[k]}")
        if len(conflicts) > 10:
            print(f"    ... 共 {len(conflicts)} 条")
        overwrite = _prompt("是否用源词典覆盖？(y/n)", "n").lower()
        if overwrite != "y":
            print("  已取消。")
            return

    dst_data["terms"].update(src_terms)
    save_dict(dst_path, dst_data)
    print(f"  已将 {len(src_terms)} 条词条{'复制' if action == 'c' else '移动'}到目标词典。")

    if action == "m":
        confirm_del = _prompt(
            f"  确认从「{src_data['meta'].get('name', src_path.stem)}」删除这 {len(src_terms)} 条词条？(y/n)",
            "n",
        ).lower()
        if confirm_del == "y":
            src_data["terms"].clear()
            save_dict(src_path, src_data)
            print("  源词典词条已清空。")
        else:
            print("  源词典保持不变（执行了复制而非移动）。")

    _pause()


def _menu_dict_operations(path: Path, data: dict) -> None:
    """单个词典的操作子菜单。"""
    name = data["meta"].get("name", path.stem)
    while True:
        _print_header(f"操作词典：{name}")
        print("  1. 查看所有词条")
        print("  2. 添加词条")
        print("  3. 删除词条")
        print("  4. 批量迁移词条到其他词典")
        print("  0. 返回主菜单")

        choice = _prompt("\n请选择操作")
        if choice == "1":
            _menu_view_terms(path, data)
        elif choice == "2":
            _menu_add_term(path, data)
            # 重新加载以获取最新数据
            data = load_dict(path)
        elif choice == "3":
            _menu_delete_term(path, data)
            data = load_dict(path)
        elif choice == "4":
            _menu_migrate_terms(path, data)
            data = load_dict(path)
        elif choice == "0":
            break
        else:
            print("  无效选项，请重新输入。")


def _menu_create_ip_dict() -> None:
    """创建新 IP 词典。"""
    _print_header("创建新 IP 词典")
    name = _prompt("请输入文件名（英文，不含 .json，如 harry_potter）")
    if not name:
        print("  已取消。")
        return
    # 基本合法性检查
    import re
    if not re.match(r"^[\w\-]+$", name):
        print("  文件名只能包含字母、数字、下划线和连字符。")
        return
    display = _prompt(f"请输入词典显示名称", name)
    try:
        path = create_ip_dict(name, display)
        print(f"  已创建：{path}")
    except FileExistsError as e:
        print(f"  {e}")
    _pause()


# ──────────────────────────────────────────────
# 主菜单入口
# ──────────────────────────────────────────────


def run_cli() -> None:
    """启动 CLI 词典编辑器。"""
    while True:
        _print_header("ATO3 词典编辑器")
        print("\n  当前可用词典：\n")
        paths = _show_dict_list()
        print("\n  ─────────────────────────────")
        print("  [s] 选择词典进行编辑")
        print("  [n] 创建新 IP 词典")
        print("  [q] 退出")

        choice = _prompt("\n请选择操作").lower()

        if choice == "s":
            if not paths:
                print("  暂无词典，请先创建。")
                _pause()
                continue
            print("\n  请选择要编辑的词典：\n")
            result = _select_dict()
            if result:
                path, data = result
                _menu_dict_operations(path, data)

        elif choice == "n":
            _menu_create_ip_dict()

        elif choice == "q":
            print("\n  再见！")
            break

        else:
            print("  无效选项，请重新输入。")


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    run_cli()
