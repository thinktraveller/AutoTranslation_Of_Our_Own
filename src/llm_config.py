"""
llm_config.py — LLM 配置模块

功能：
  - 读取 config.json 中的提供商与 agent 配置
  - 从 .env 中加载 API Key 环境变量
  - 提供 get_client(agent_name, profile_config) 获取对应 openai.OpenAI 实例
  - 提供 get_profile_config(profile_name) 按四级优先级加载模型方案配置
  - 直接运行（python llm_config.py）进入 CLI 交互式配置编辑器（含方案管理）

用法（作为模块导入）：
    from llm_config import get_client, get_agent_config, get_profile_config
    profile_cfg = get_profile_config("balanced")
    client, config = get_client("translator", profile_config=profile_cfg)
    response = client.chat.completions.create(
        model=config["model"],
        messages=[...],
        temperature=config["temperature"],
    )
"""

import copy
import json
import os
import sys
from pathlib import Path
from typing import Optional

# 尝试加载 .env 文件（需要 python-dotenv）
try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False

# 尝试导入 openai SDK
try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

# 项目根目录（src/ 的上一级目录）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CONFIG_PATH = PROJECT_ROOT / "config.json"
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env() -> None:
    """加载 .env 文件中的环境变量。"""
    if not _DOTENV_AVAILABLE:
        return
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
    # 若 .env 不存在，不报错，环境变量可能已通过其他方式设置


def load_config() -> dict:
    """
    读取并返回 config.json 内容。

    Returns:
        dict: 配置字典，包含 "providers" 和 "agents" 两个顶层键。

    Raises:
        FileNotFoundError: config.json 不存在时抛出。
        json.JSONDecodeError: config.json 格式不合法时抛出。
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"找不到配置文件：{CONFIG_PATH}\n"
            "请确认项目根目录下存在 config.json，或运行 python llm_config.py 创建默认配置。"
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """将配置写回 config.json（格式化 JSON，UTF-8 编码）。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_agent_config(agent_name: str) -> dict:
    """
    获取指定 agent 的完整配置（合并 agent 自身配置与其提供商配置）。

    Args:
        agent_name: agent 名称，如 "translator"、"term_extractor"、"polisher"

    Returns:
        dict，包含以下字段：
            - provider: 提供商名称
            - base_url: API 基础 URL
            - api_key_env: API Key 的环境变量名
            - model: 模型名
            - temperature: 温度参数

    Raises:
        KeyError: agent 或 provider 不存在时抛出，附带可读错误信息。
    """
    config = load_config()

    if agent_name not in config.get("agents", {}):
        available = list(config.get("agents", {}).keys())
        raise KeyError(
            f"未找到 agent 配置：'{agent_name}'\n"
            f"当前已配置的 agents：{available}\n"
            f"请运行 python llm_config.py 添加或修改 agent 配置。"
        )

    agent_cfg = config["agents"][agent_name]
    provider_name = agent_cfg["provider"]

    if provider_name not in config.get("providers", {}):
        available = list(config.get("providers", {}).keys())
        raise KeyError(
            f"agent '{agent_name}' 引用了不存在的提供商：'{provider_name}'\n"
            f"当前已配置的提供商：{available}\n"
            f"请运行 python llm_config.py 添加提供商配置。"
        )

    provider_cfg = config["providers"][provider_name]

    # 将 agent 的所有字段合并返回（包含 polish_batch_mode、system_prompt 等自定义字段）
    result = {**agent_cfg}
    result.update({
        "provider": provider_name,
        "base_url": provider_cfg["base_url"],
        "api_key_env": provider_cfg["api_key_env"],
        "model": agent_cfg["model"],
        "temperature": agent_cfg.get("temperature", 0.3),
    })
    return result


def get_profile_config(profile_name: str | None = None) -> dict:
    """
    返回指定 profile 下各 agent 的配置字典（深拷贝）。

    查找优先级：
      1. 显式传入的 profile_name
      2. config.json 的 default_profile 字段
      3. config.json 的顶层 agents 字段（旧版兼容）
      4. 内置硬编码默认值（config.json 缺失时的最后兜底）

    Args:
        profile_name: 方案名称（如 "fast" / "balanced" / "quality"），None 表示自动选择

    Returns:
        dict，包含 "term_extractor" / "translator" / "polisher" 三个键，
        每个键对应该 agent 的配置（provider / model / temperature）。
    """
    # 内置硬编码默认方案（config.json 完全缺失时的最后兜底）
    _BUILTIN_PROFILES: dict[str, dict] = {
        "fast": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
        },
        "balanced": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "openai",   "model": "gpt-4o-mini",   "temperature": 0.5},
        },
        "quality": {
            "term_extractor": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1},
            "translator":     {"provider": "openai", "model": "gpt-4o",      "temperature": 0.3},
            "polisher":       {"provider": "openai", "model": "gpt-4o",      "temperature": 0.5},
        },
    }
    _HARDCODED_DEFAULT = copy.deepcopy(_BUILTIN_PROFILES["balanced"])

    try:
        cfg = load_config()
    except (FileNotFoundError, json.JSONDecodeError):
        # config.json 不存在或无法解析：使用硬编码兜底
        if profile_name and profile_name in _BUILTIN_PROFILES:
            return copy.deepcopy(_BUILTIN_PROFILES[profile_name])
        return _HARDCODED_DEFAULT

    # 从 config.json 加载已定义的方案（文件方案优先于内置预设）
    file_profiles: dict[str, dict] = cfg.get("profiles", {})
    # 合并：内置预设 + 文件方案（文件方案可覆盖同名内置预设）
    merged_profiles = {**_BUILTIN_PROFILES, **file_profiles}

    # 确定要使用的方案名
    name = profile_name or cfg.get("default_profile")

    if name and name in merged_profiles:
        return copy.deepcopy(merged_profiles[name])

    # 兜底：返回顶层 agents 字段（旧版兼容）
    if "agents" in cfg:
        return copy.deepcopy(cfg["agents"])

    return _HARDCODED_DEFAULT


def get_client(agent_name: str, profile_config: dict | None = None):
    """
    获取指定 agent 对应的 (openai.OpenAI 实例, agent配置字典) 元组。

    Args:
        agent_name: agent 名称（如 "translator"、"polisher"、"term_extractor"）
        profile_config: 由 get_profile_config() 返回的方案配置字典。
            若不为 None，优先从其中取 agent 配置（包含 provider/model/temperature），
            再与 config.json 中的提供商配置（base_url/api_key_env）合并；
            若为 None，沿用现有逻辑（从 config.json 的 agents 字段读取）。

    Returns:
        (OpenAI client, agent_config_dict)

    Raises:
        ImportError: openai SDK 未安装时抛出。
        EnvironmentError: API Key 环境变量未设置时抛出。
        KeyError: agent 或 provider 配置缺失时抛出。
    """
    if not _OPENAI_AVAILABLE:
        raise ImportError(
            "openai SDK 未安装，请先执行：\n"
            "  pip install openai>=1.30\n"
            "（国内推荐使用镜像）：\n"
            "  pip install openai>=1.30 -i https://pypi.tuna.tsinghua.edu.cn/simple"
        )

    _load_env()

    if profile_config is not None and agent_name in profile_config:
        # 使用方案配置中的 agent 配置，合并提供商的 base_url / api_key_env
        profile_agent = dict(profile_config[agent_name])
        provider_name = profile_agent.get("provider")
        try:
            config = load_config()
            providers = config.get("providers", {})
        except Exception:
            providers = {}

        if provider_name and provider_name in providers:
            prov = providers[provider_name]
            agent_cfg = {
                "provider": provider_name,
                "base_url": prov["base_url"],
                "api_key_env": prov["api_key_env"],
                **profile_agent,
            }
        elif provider_name:
            # 提供商不在 config.json 中，尝试从旧版 agents 兜底
            try:
                fallback = get_agent_config(agent_name)
                agent_cfg = {**fallback, **profile_agent}
            except Exception:
                raise KeyError(
                    f"Profile 中指定的提供商 '{provider_name}' 未在 config.json 中配置，"
                    f"且无法从旧版 agents 字段回退。请先运行 python -m src.llm_config 添加提供商。"
                )
        else:
            # profile_agent 无 provider，回退到标准逻辑
            agent_cfg = get_agent_config(agent_name)
    else:
        # 无 profile_config，使用旧版逻辑
        agent_cfg = get_agent_config(agent_name)

    api_key_env = agent_cfg["api_key_env"]
    api_key = os.environ.get(api_key_env)

    if not api_key:
        env_path_hint = str(ENV_PATH)
        raise EnvironmentError(
            f"API Key 未配置：环境变量 '{api_key_env}' 未设置或为空。\n"
            f"请在 {env_path_hint} 中添加：\n"
            f"  {api_key_env}=your-api-key-here\n"
            f"（参考 .env.example 文件的格式）"
        )

    client = OpenAI(
        api_key=api_key,
        base_url=agent_cfg["base_url"],
    )
    return client, agent_cfg


# ---------------------------------------------------------------------------
# CLI 交互式配置编辑器
# ---------------------------------------------------------------------------

def _print_separator(char="─", width=50):
    print(char * width)


def _show_current_config(config: dict) -> None:
    """打印当前配置的可读摘要。"""
    _print_separator()
    print("当前提供商配置：")
    for name, prov in config.get("providers", {}).items():
        env_val = os.environ.get(prov["api_key_env"], "（未设置）")
        key_status = "已设置" if env_val and env_val != "（未设置）" else "未设置"
        print(f"  [{name}]  base_url={prov['base_url']}  API Key({prov['api_key_env']})={key_status}")

    print()
    print("当前 Agent 配置：")
    for name, agent in config.get("agents", {}).items():
        print(f"  [{name}]  provider={agent['provider']}  model={agent['model']}  temperature={agent.get('temperature', 0.3)}")
    _print_separator()


def _edit_provider(config: dict) -> None:
    """交互式添加或修改提供商。"""
    print("\n--- 编辑提供商 ---")
    print("已有提供商：", list(config.get("providers", {}).keys()))
    name = input("请输入提供商名称（新建或修改已有）：").strip()
    if not name:
        print("名称不能为空，操作取消。")
        return

    existing = config.setdefault("providers", {}).get(name, {})
    default_url = existing.get("base_url", "https://api.openai.com/v1")
    default_env = existing.get("api_key_env", f"{name.upper()}_API_KEY")

    base_url = input(f"base_url [{default_url}]：").strip() or default_url

    print("  （此处填写环境变量的【名称】，例如 OPENAI_API_KEY；实际密钥值请写入 .env 文件）")
    api_key_env = input(f"API Key 环境变量名 [{default_env}]：").strip() or default_env

    # 防误填：若输入值看起来是密钥本身（含非字母下划线字符且较长），给出警告
    import re as _re
    if len(api_key_env) > 30 or _re.search(r'[^A-Z0-9_a-z]', api_key_env):
        print(f"  ⚠️  警告：'{api_key_env}' 看起来像密钥值而非变量名。")
        print(f"       变量名应为全大写字母+下划线格式，例如：{default_env}")
        print(f"       实际密钥请写入 .env 文件：{api_key_env[:4]}... = <你的密钥>")
        confirm = input("  确认使用此值作为环境变量名？(y/N)：").strip().lower()
        if confirm != 'y':
            print("  操作取消，请重新运行并填写正确的变量名。")
            return

    config["providers"][name] = {"base_url": base_url, "api_key_env": api_key_env}
    save_config(config)
    print(f"提供商 '{name}' 已保存。")
    print(f"  → 请在项目根目录的 .env 文件中添加：{api_key_env}=你的密钥")


def _edit_agent(config: dict) -> None:
    """交互式修改 agent 配置。"""
    print("\n--- 编辑 Agent ---")
    print("已有 agents：", list(config.get("agents", {}).keys()))
    name = input("请输入 agent 名称（新建或修改已有）：").strip()
    if not name:
        print("名称不能为空，操作取消。")
        return

    existing = config.setdefault("agents", {}).get(name, {})
    providers = list(config.get("providers", {}).keys())
    default_provider = existing.get("provider", providers[0] if providers else "openai")
    default_model = existing.get("model", "gpt-4o")
    default_temp = existing.get("temperature", 0.3)

    print(f"可用提供商：{providers}")
    provider = input(f"provider [{default_provider}]：").strip() or default_provider
    model = input(f"model [{default_model}]：").strip() or default_model
    temp_str = input(f"temperature [{default_temp}]：").strip()
    temperature = float(temp_str) if temp_str else default_temp

    # 保留已有自定义字段（如 polish_batch_mode、polish_context_token_limit、system_prompt）
    existing_agent = config.get("agents", {}).get(name, {})
    updated_agent = {**existing_agent}
    updated_agent["provider"] = provider
    updated_agent["model"] = model
    updated_agent["temperature"] = temperature
    config["agents"][name] = updated_agent
    save_config(config)
    print(f"Agent '{name}' 已保存。")


def _edit_agent_prompt(config: dict) -> None:
    """
    查看或编辑 agent 的系统提示词。
    提示词存储在 config.json 的 agents.<name>.system_prompt 字段中（可选）。
    若字段不存在，各 agent 模块将使用其内置默认提示词。
    """
    print("\n--- 查看/编辑 Agent 提示词 ---")
    agents = list(config.get("agents", {}).keys())
    if not agents:
        print("暂无 agent 配置。")
        return
    print("已有 agents：", agents)
    name = input("请输入要编辑的 agent 名称（回车取消）：").strip()
    if not name:
        print("操作取消。")
        return
    if name not in config.get("agents", {}):
        print(f"Agent '{name}' 不存在。")
        return

    agent_data = config["agents"][name]
    current_prompt = agent_data.get("system_prompt", "")

    if current_prompt:
        print(f"\n当前自定义提示词（{len(current_prompt)} 字符）：")
        print("-" * 40)
        print(current_prompt[:500] + ("..." if len(current_prompt) > 500 else ""))
        print("-" * 40)
    else:
        print(f"\n当前未设置自定义提示词（将使用 {name} 模块内置默认值）。")

    print()
    print("操作：[e] 编辑提示词  [d] 删除自定义提示词（恢复默认）  [q] 取消")
    action = input("请选择：").strip().lower()

    if action == "d":
        if "system_prompt" in agent_data:
            del agent_data["system_prompt"]
            save_config(config)
            print(f"已删除 agent '{name}' 的自定义提示词，将使用模块默认值。")
        else:
            print("当前无自定义提示词，无需删除。")
    elif action == "e":
        print()
        print("请逐行输入新的系统提示词。")
        print("输入完成后，在新的一行只输入「END」（不含引号）并回车确认。")
        print("输入「CANCEL」取消操作。")
        print("-" * 40)
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "END":
                break
            if line.strip() == "CANCEL":
                print("操作取消，提示词未修改。")
                return
            lines.append(line)
        new_prompt = "\n".join(lines).strip()
        if not new_prompt:
            print("提示词为空，操作取消。")
            return
        agent_data["system_prompt"] = new_prompt
        save_config(config)
        print(f"已保存 agent '{name}' 的自定义提示词（{len(new_prompt)} 字符）。")
        print("注意：各 agent 模块会在下次调用时优先使用 config.json 中的提示词。")
    else:
        print("操作取消。")


def _delete_provider(config: dict) -> None:
    """删除提供商（若有 agent 引用则警告）。"""
    print("\n--- 删除提供商 ---")
    print("已有提供商：", list(config.get("providers", {}).keys()))
    name = input("请输入要删除的提供商名称：").strip()
    if name not in config.get("providers", {}):
        print(f"提供商 '{name}' 不存在。")
        return

    refs = [a for a, c in config.get("agents", {}).items() if c.get("provider") == name]
    if refs:
        print(f"警告：以下 agents 正在引用此提供商：{refs}")
        confirm = input("确认删除？(y/n)：").strip().lower()
        if confirm != "y":
            print("操作取消。")
            return

    del config["providers"][name]
    save_config(config)
    print(f"提供商 '{name}' 已删除。")


# ---------------------------------------------------------------------------
# Profile 管理菜单
# ---------------------------------------------------------------------------

# 内置预设方案（不可删除，仅可被用户同名方案覆盖）
_BUILTIN_PROFILE_NAMES = {"fast", "balanced", "quality"}

_BUILTIN_PROFILES_DESC = {
    "fast":     "全程 DeepSeek（速度快、成本低）",
    "balanced": "DeepSeek 翻译 + GPT-4o-mini 润色（推荐）",
    "quality":  "全程 OpenAI GPT-4o（质量最优）",
}


def _show_profiles(config: dict) -> None:
    """打印所有方案的摘要信息。"""
    # 内置预设方案
    builtin: dict[str, dict] = {
        "fast": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
        },
        "balanced": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "openai",   "model": "gpt-4o-mini",   "temperature": 0.5},
        },
        "quality": {
            "term_extractor": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1},
            "translator":     {"provider": "openai", "model": "gpt-4o",      "temperature": 0.3},
            "polisher":       {"provider": "openai", "model": "gpt-4o",      "temperature": 0.5},
        },
    }

    file_profiles: dict = config.get("profiles", {})
    default_name: str = config.get("default_profile", "")

    all_names = list(builtin.keys()) + [k for k in file_profiles if k not in builtin]
    _print_separator()
    print("所有可用模型方案：")
    for name in all_names:
        is_default = "（默认）" if name == default_name else ""
        is_builtin = "（内置）" if name in builtin else "（自定义）"
        # 取实际配置（自定义覆盖内置）
        profile = file_profiles.get(name, builtin.get(name, {}))
        print(f"  [{name}] {is_builtin}{is_default}")
        for agent_key in ("term_extractor", "translator", "polisher"):
            ac = profile.get(agent_key, {})
            print(f"    {agent_key}: provider={ac.get('provider','?')}  model={ac.get('model','?')}  temperature={ac.get('temperature','?')}")
    _print_separator()


def _new_or_edit_profile(config: dict, edit_name: str | None = None) -> None:
    """
    新建或编辑方案。
    edit_name: 若不为 None，则编辑已有方案；否则新建。
    """
    providers = list(config.get("providers", {}).keys())

    if edit_name is None:
        print("\n--- 新建模型方案 ---")
        name = input("请输入新方案名称（字母/数字/下划线）：").strip()
        if not name:
            print("名称不能为空，操作取消。")
            return
    else:
        print(f"\n--- 编辑方案：{edit_name} ---")
        name = edit_name

    file_profiles: dict = config.setdefault("profiles", {})

    # 内置预设（作为编辑起始值的参考）
    _builtin: dict[str, dict] = {
        "fast": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
        },
        "balanced": {
            "term_extractor": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1},
            "translator":     {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3},
            "polisher":       {"provider": "openai",   "model": "gpt-4o-mini",   "temperature": 0.5},
        },
        "quality": {
            "term_extractor": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1},
            "translator":     {"provider": "openai", "model": "gpt-4o",      "temperature": 0.3},
            "polisher":       {"provider": "openai", "model": "gpt-4o",      "temperature": 0.5},
        },
    }

    # 取现有值：优先使用文件中的方案，其次使用内置预设，再次使用 balanced
    existing = file_profiles.get(name, _builtin.get(name, copy.deepcopy(_builtin["balanced"])))

    new_profile: dict = {}
    print(f"  可用提供商：{providers}（直接回车保持不变）")
    for agent_key in ("term_extractor", "translator", "polisher"):
        print(f"  --- {agent_key} ---")
        cur = existing.get(agent_key, {})
        cur_provider = cur.get("provider", "deepseek")
        cur_model = cur.get("model", "deepseek-chat")
        cur_temp = cur.get("temperature", 0.3)

        prov = input(f"    提供商 [当前: {cur_provider}]：").strip() or cur_provider
        model = input(f"    模型   [当前: {cur_model}]：").strip() or cur_model
        temp_str = input(f"    temperature [当前: {cur_temp}]：").strip()
        temperature = float(temp_str) if temp_str else cur_temp

        new_profile[agent_key] = {"provider": prov, "model": model, "temperature": temperature}

    file_profiles[name] = new_profile
    save_config(config)
    print(f"方案 '{name}' 已保存。")


def _delete_profile(config: dict) -> None:
    """删除自定义方案（内置三个方案不可删除）。"""
    print("\n--- 删除模型方案 ---")
    file_profiles: dict = config.get("profiles", {})
    custom_names = [k for k in file_profiles if k not in _BUILTIN_PROFILE_NAMES]
    if not custom_names:
        print("当前没有可删除的自定义方案（内置方案 fast/balanced/quality 不可删除）。")
        return
    print("可删除的自定义方案：", custom_names)
    name = input("请输入要删除的方案名称：").strip()
    if name in _BUILTIN_PROFILE_NAMES:
        print(f"  内置方案 '{name}' 不可删除（可在 config.json 中同名定义以覆盖其配置）。")
        return
    if name not in file_profiles:
        print(f"  方案 '{name}' 不存在。")
        return

    # 若删除的是当前 default_profile，同步清空
    if config.get("default_profile") == name:
        print(f"  注意：方案 '{name}' 当前为 default_profile，将自动重置为 'balanced'。")
        config["default_profile"] = "balanced"

    del file_profiles[name]
    save_config(config)
    print(f"方案 '{name}' 已删除。")


def _set_default_profile(config: dict) -> None:
    """将某方案设为 default_profile。"""
    print("\n--- 设为默认方案 ---")
    file_profiles: dict = config.get("profiles", {})
    all_names = list(_BUILTIN_PROFILE_NAMES) + [k for k in file_profiles if k not in _BUILTIN_PROFILE_NAMES]
    print("可用方案：", all_names)
    name = input("请输入要设为默认的方案名称：").strip()
    if name not in all_names:
        print(f"  方案 '{name}' 不存在。")
        return
    config["default_profile"] = name
    save_config(config)
    print(f"已将 '{name}' 设为默认方案（default_profile）。")


def _manage_profiles(config: dict) -> None:
    """方案管理子菜单。"""
    # 若当前配置仍是纯旧版结构（无 profiles），提示但不强制迁移
    if "profiles" not in config and "agents" in config:
        print()
        print("  提示：当前使用旧版配置结构（仅含 agents 字段，无 profiles）。")
        print("  方案管理功能可正常使用；新建方案后将写入 profiles 字段。")
        print("  如需迁移，可在「新建方案」中创建与 agents 等价的方案，再设为默认。")

    while True:
        print()
        print("  方案管理子菜单：")
        print("    5-1. 查看所有方案")
        print("    5-2. 新建方案")
        print("    5-3. 编辑方案")
        print("    5-4. 删除方案（内置三个方案不可删除）")
        print("    5-5. 设为默认方案（修改 default_profile）")
        print("    5-0. 返回主菜单")
        sub = input("  输入子菜单编号：").strip()

        config = load_config()  # 每次操作前重新加载
        if sub in ("5-1", "51"):
            _show_profiles(config)
        elif sub in ("5-2", "52"):
            _new_or_edit_profile(config, edit_name=None)
        elif sub in ("5-3", "53"):
            file_profiles: dict = config.get("profiles", {})
            all_names = list(_BUILTIN_PROFILE_NAMES) + [k for k in file_profiles if k not in _BUILTIN_PROFILE_NAMES]
            print("  可编辑方案：", all_names)
            ename = input("  请输入要编辑的方案名称：").strip()
            if ename:
                _new_or_edit_profile(config, edit_name=ename)
            else:
                print("  操作取消。")
        elif sub in ("5-4", "54"):
            _delete_profile(config)
        elif sub in ("5-5", "55"):
            _set_default_profile(config)
        elif sub in ("5-0", "50", "0", ""):
            print("  返回主菜单。")
            break
        else:
            print("  无效选项，请重新输入。")


def run_cli() -> None:
    """CLI 交互式配置编辑器入口。"""
    _load_env()

    print()
    print("ATO3 LLM 配置编辑器")
    _print_separator("=")

    try:
        config = load_config()
    except FileNotFoundError:
        print("未找到 config.json，将创建默认配置...")
        config = {
            "providers": {
                "openai": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY"
                }
            },
            "agents": {
                "term_extractor": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1},
                "translator": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.3},
                "polisher": {"provider": "openai", "model": "gpt-4o", "temperature": 0.7}
            }
        }
        save_config(config)
        print(f"默认配置已写入：{CONFIG_PATH}")

    _show_current_config(config)

    while True:
        print()
        print("请选择操作：")
        print("  1. 查看当前配置")
        print("  2. 添加/修改提供商")
        print("  3. 添加/修改 Agent（模型/提供商/温度）")
        print("  4. 查看/编辑 Agent 提示词")
        print("  5. 管理模型方案（Profile）")
        print("  6. 删除提供商")
        print("  7. 退出")
        choice = input("输入数字：").strip()

        if choice == "1":
            config = load_config()
            _show_current_config(config)
        elif choice == "2":
            config = load_config()
            _edit_provider(config)
        elif choice == "3":
            config = load_config()
            _edit_agent(config)
        elif choice == "4":
            config = load_config()
            _edit_agent_prompt(config)
        elif choice == "5":
            config = load_config()
            _manage_profiles(config)
        elif choice == "6":
            config = load_config()
            _delete_provider(config)
        elif choice == "7":
            print("退出配置编辑器。")
            break
        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    run_cli()
