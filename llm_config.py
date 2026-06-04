"""llm_config.py — 根目录转发入口，实际实现在 src/llm_config.py"""
from src.llm_config import *  # noqa: F401, F403
from src.llm_config import run_cli

if __name__ == '__main__':
    run_cli()
