# ATO3 — Auto Translation Of Our Own

> 将 AO3 同人作品从外文自动翻译为简体中文，输出 txt / Markdown / docx 三种格式。

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [快速上手](#快速上手)
- [依赖安装](#依赖安装)
- [配置说明](#配置说明)
- [使用方法](#使用方法)
- [翻译流程](#翻译流程)
- [词典系统](#词典系统)
- [断点续传](#断点续传)
- [输出格式](#输出格式)
- [项目结构](#项目结构)
- [许可证](#许可证)

---

## 项目简介

ATO3（Auto Translation Of Our Own）是一个面向同人文爱好者的本地翻译工具，专为处理从 [Archive of Our Own](https://archiveofourown.org/) 下载的 HTML 文件而设计。

工具通过调用兼容 OpenAI API 的大语言模型（如 DeepSeek、GPT-4o 等），完成**术语提取 → 翻译 → 润色**三阶段流水线，并在关键节点暂停以供人工精校，最终输出可直接阅读或分发的文档。

---

## 功能特性

- **全流程自动化**：解析 AO3 HTML → 术语提取 → 翻译 → 润色 → 输出，一条命令完成
- **交互式精校**：翻译完成后暂停，支持在外部编辑器精校 txt，精校结果自动回填 Markdown 和 docx
- **词典系统**：通用词典（通用译名规范）+ IP 词典（作品专属术语），支持自动推断和手动指定
- **断点续传**：任意阶段可保存进度退出，下次启动自动恢复，支持 Ctrl+C 中断
- **多模型方案**：通过 `config.json` 灵活配置 term_extractor / translator / polisher 三个角色各自的模型
- **多格式输出**：同时生成 `.txt`、`.md`、`.docx`，docx 支持自定义 Word 模板
- **多语言支持**：默认英文，可指定日、韩、法、德、西班牙、俄等源语言

---

## 快速上手

```bash
# 1. 克隆项目
git clone https://github.com/thinktraveller/AutoTranslation_Of_Our_Own.git
cd AutoTranslation_Of_Our_Own

# 2. 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate     # macOS / Linux

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 API Key
copy .env.example .env
# 用文本编辑器打开 .env，填入你的 API Key

# 5. 配置模型方案
python -m src.llm_config

# 6. 运行（交互模式）
python main.py
```

---

## 依赖安装

### 系统依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| Python 3.10+ | 运行环境 | [python.org](https://www.python.org/downloads/) |
| pandoc | 生成 docx | [pandoc.org](https://pandoc.org/installing.html) |

### Python 依赖

```bash
pip install -r requirements.txt
```

> 💡 **中国大陆网络**：添加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 使用清华镜像

主要依赖包：

| 包名 | 用途 |
|------|------|
| `openai` | 调用兼容 OpenAI API 的 LLM |
| `python-dotenv` | 读取 `.env` 中的 API Key |
| `beautifulsoup4` | 解析 AO3 HTML |
| `python-docx` | docx 后处理 |

---

## 配置说明

### 1. API Key（`.env`）

复制 `.env.example` 为 `.env`，填入 API Key：

```ini
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
OPENAI_API_KEY=sk-your-openai-key-here
# 其他兼容 OpenAI API 的提供商按需添加
```

`.env` 文件**绝对不能提交到 Git 仓库**，已在 `.gitignore` 中屏蔽。

### 2. 模型方案（`config.json`）

运行交互式配置编辑器：

```bash
python -m src.llm_config
```

或手动编辑 `config.json`。配置结构示例：

```json
{
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com/v1",
      "api_key_env": "DEEPSEEK_API_KEY"
    }
  },
  "default_profile": "general",
  "profiles": {
    "general": {
      "term_extractor": { "provider": "deepseek", "model": "deepseek-chat", "temperature": 0.1 },
      "translator":     { "provider": "deepseek", "model": "deepseek-chat", "temperature": 0.3 },
      "polisher":       { "provider": "deepseek", "model": "deepseek-chat", "temperature": 0.8 }
    }
  }
}
```

`config.json` 包含本地配置（如私有模型地址），**不提交到 Git 仓库**。

---

## 使用方法

### 交互模式（推荐新手）

```bash
python main.py
```

程序会逐步提示你选择：HTML 文件路径、模型方案、源语言、IP 词典等。

### 命令行模式

```bash
python main.py <html_file> [选项]
```

**常用选项：**

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--profile NAME` | 模型方案名称 | config.json 中的 `default_profile` |
| `--source-lang LANG` | 源语言代码（en/ja/ko/fr/de/es/ru） | `en` |
| `--ip-dict PATH` | IP 词典路径 | 按 HTML 文件名自动推断 |
| `--general-dict PATH` | 通用词典路径 | `dicts/general.json` |
| `--no-general-dict` | 不加载通用词典 | — |
| `--skip-term-extract` | 跳过术语提取，直接使用已有词典 | — |
| `--skip-polish` | 跳过润色步骤 | — |
| `--docx-template PATH` | pandoc `--reference-doc` 模板 | `markdown-to-docx/ATO3_template.dotx`（若存在） |
| `--output-dir PATH` | 输出目录 | HTML 同级同名文件夹 |

**示例：**

```bash
# 翻译英文作品，使用 general 方案，跳过润色
python main.py "downloads/my_fic.html" --profile general --skip-polish

# 翻译日文作品，指定 IP 词典
python main.py "downloads/jp_fic.html" --source-lang ja --ip-dict dicts/ip/myip.json
```

---

## 翻译流程

```
HTML 文件
    │
    ▼
[1] 解析 HTML          解析 AO3 页面结构，提取标题、作者、标签、摘要、
                        前言/尾注、正文段落
    │
    ▼
[2] 加载词典           合并通用词典 + IP 词典 → 术语表
    │
    ▼
[3] 术语提取 *         LLM 从全文提取作品专属术语，人工确认后写入 IP 词典
    │         ← 断点 1：术语确认后（可保存退出）
    ▼
[4] 翻译               LLM 逐段翻译全文（支持断点续传，Ctrl+C 可中断保存）
    │
    ▼
[5] 润色 *             LLM 对译文进行语言润色，提升可读性
    │
    ▼
[6] 输出 txt           生成纯文本译文，供人工精校
    │         ← 断点 2：请在编辑器中完成精校，输入 y 继续
    ▼
[7] 输出 Markdown      将精校后 txt 转为结构化 Markdown
    │         ← 断点 3：检视 Markdown 格式，输入 y 继续
    ▼
[8] 输出 docx          调用 pandoc 生成 Word 文档（可应用 .dotx 模板）
```

`*` 标注的步骤可通过 `--skip-term-extract` / `--skip-polish` 跳过。

---

## 词典系统

### 通用词典（`dicts/general.json`）

存放跨作品通用的译名规范，如标点符号处理、常见英文表达等。所有任务均默认加载。

### IP 词典（`dicts/ip/`）

存放特定作品 IP 的专属术语，格式示例：

```json
{
  "meta": {
    "name": "我的作品词典",
    "version": "1.0",
    "remarks": ["关键词1", "关键词2"]
  },
  "terms": {
    "character name": "角色中文名",
    "place name": "地名译名"
  }
}
```

`remarks` 字段用于自动匹配：程序会统计这些关键词在 HTML 全文中的出现频率，自动推荐最匹配的 IP 词典。

### 词典索引（`dicts/dict_index.json`）

记录所有 IP 词典与其 `remarks` 关键词的映射，供自动匹配算法使用。

> ⚠️ IP 词典和词典索引文件包含版权 IP 内容，**不纳入版本控制**。

---

## 断点续传

ATO3 提供两种断点续传机制：

### 主动保存（任务断点）

在以下三处暂停节点，输入 `s` 可保存当前进度并退出：

- **断点 1**：术语确认完成后
- **断点 2**：txt 精校确认时
- **断点 3**：Markdown 检视确认时

下次运行 `python main.py`（无参数，交互模式）时，程序会自动列出未完成任务，选择序号即可从断点继续。

### 自动保存（翻译检查点）

翻译阶段每完成一段就写入检查点文件（`logs/<任务名>/progress.json`）。遇到网络错误或 Ctrl+C 中断时，重新运行相同命令将自动从上次已完成的段落继续，**不重复翻译已完成的内容**。

---

## 输出格式

翻译完成后，在输出目录（默认为 HTML 同级的同名子文件夹）生成三个文件：

| 文件 | 用途 |
|------|------|
| `<作品名>.txt` | 纯文本译文，供精校使用 |
| `<作品名>.md` | 结构化 Markdown，包含标题、标签、摘要等元数据 |
| `<作品名>.docx` | Word 文档，可应用自定义样式模板 |

### docx 模板

项目内置 Word 模板（`markdown-to-docx/ATO3_template.dotx`），交互模式下会自动检测并提示使用。也可通过 `--docx-template` 指定其他模板。

---

## 项目结构

```
AutoTranslation_Of_Our_Own/
├── main.py                     # 主入口：CLI 解析、流程调度、断点续传
├── config.json                 # 模型方案配置（本地，不提交）
├── .env                        # API Key（本地，不提交）
├── .env.example                # API Key 配置模板
│
├── src/                        # 核心模块
│   ├── html_parser.py          # AO3 HTML 解析
│   ├── term_extractor.py       # LLM 术语提取与 CLI 确认
│   ├── translator.py           # LLM 翻译（支持检查点续传）
│   ├── polisher.py             # LLM 润色
│   ├── output_writer.py        # txt / Markdown / docx 输出
│   ├── dict_manager.py         # 词典加载、合并、保存
│   ├── llm_config.py           # 模型方案配置读取与交互式编辑器
│   └── llm_logger.py           # LLM 调用日志记录
│
├── dicts/                      # 词典目录
│   ├── general.json            # 通用词典
│   ├── dict_index.json         # IP 词典索引（本地，不提交）
│   └── ip/                     # IP 专属词典目录（本地，不提交）
│
├── logs/                       # 运行日志（本地，不提交）
│   └── <作品名>_<时间戳>/
│       ├── task_state.json     # 任务断点状态
│       └── progress.json       # 翻译检查点
│
└── markdown-to-docx/           # Markdown → docx 转换技能
    ├── SKILL.md                # 技能说明
    ├── ATO3_template.dotx      # 内置 Word 样式模板
    └── scripts/
        ├── convert_markdown_to_docx.sh    # 批量转换脚本
        ├── postprocess_template_docx.py   # docx 后处理
        ├── template_style_filter.lua      # pandoc lua filter
        ├── render_mermaid_blocks_for_docx.py
        ├── render_markdown_with_dotx.sh
        └── validate_captions.py
```

---

## 许可证

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.zh) 许可证。

**您可以自由地：**
- 分享 — 在任何媒介以任何形式复制、发行本作品
- 演绎 — 修改、转换或以本作品为基础进行创作

**须遵守以下条件：**
- **署名** — 您必须给出适当的署名，提供指向本许可证的链接，并标明是否对原始作品作了修改
- **非商业性使用** — 您不得将本作品用于商业目的

本项目与 Archive of Our Own（AO3）及其运营方 OTW 没有任何从属关系。
