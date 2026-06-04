"""
llm_config.py — LLM 配置模块

功能：
  - 读取 config.json 中的提供商与 agent 配置
  - 从 .env 中加载 API Key 环境变量
  - 提供 get_client(agent_name) 获取对应 openai.OpenAI 实例
  - 直接运行（python llm_config.py）进入 CLI 交互式配置编辑器

用法（作为模块导入）：
    from llm_config import get_client, get_agent_config
    client, config = get_client("translator")
    response = client.chat.completions.create(
        model=config["model"],
        messages=[...],
        temperature=config["temperature"],
    )
"""

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

# 项目根目录（llm_config.py 所在目录）
PROJECT_ROOT = Path(__file__).parent.resolve()
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

    return {
        "provider": provider_name,
        "base_url": provider_cfg["base_url"],
        "api_key_env": provider_cfg["api_key_env"],
        "model": agent_cfg["model"],
        "temperature": agent_cfg.get("temperature", 0.3),
    }


def get_client(agent_name: str):
    """
    获取指定 agent 对应的 (openai.OpenAI 实例, agent配置字典) 元组。

    Args:
        agent_name: agent 名称

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
    api_key_env = input(f"API Key 环境变量名 [{default_env}]：").strip() or default_env

    config["providers"][name] = {"base_url": base_url, "api_key_env": api_key_env}
    save_config(config)
    print(f"提供商 '{name}' 已保存。")


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

    config["agents"][name] = {"provider": provider, "model": model, "temperature": temperature}
    save_config(config)
    print(f"Agent '{name}' 已保存。")


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

    menu = {
        "1": ("查看当前配置", lambda: _show_current_config(load_config())),
        "2": ("添加/修改提供商", lambda: _edit_provider(load_config()) or None),
        "3": ("添加/修改 Agent", lambda: _edit_agent(load_config()) or None),
        "4": ("删除提供商", lambda: _delete_provider(load_config()) or None),
        "5": ("退出", None),
    }

    # 对于修改操作，需要传入可变的 config 引用，重新实现菜单处理
    while True:
        print()
        print("请选择操作：")
        for key, (desc, _) in menu.items():
            print(f"  {key}. {desc}")
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
            _delete_provider(config)
        elif choice == "5":
            print("退出配置编辑器。")
            break
        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    run_cli()
