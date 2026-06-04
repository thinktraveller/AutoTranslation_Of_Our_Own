# 构建日志

## [2026-06-04 22:28] 步骤 1 完成：项目结构初始化与 LLM 配置模块

### 执行的任务
- 创建项目完整目录结构（dicts/ip/、test/ 已存在）
- 创建 config.json（包含 openai 和 deepseek 两个提供商，以及 term_extractor/translator/polisher 三个 agent 配置）
- 创建 dicts/general.json（通用词典，含 AO3 常见术语 19 条）
- 创建 .env.example（API Key 配置模板，说明格式，不含真实密钥）
- 创建 llm_config.py（核心 LLM 配置模块，支持 get_client/get_agent_config/CLI 编辑器）
- 创建各模块骨架占位文件：html_parser.py、term_extractor.py、translator.py、polisher.py、dict_manager.py、output_writer.py、main.py
- 运行 _verify/step01_check_config.py 验证通过（0 错误，0 警告）

### 关键变更
- config.json：LLM 提供商与 agent 配置，是后续所有 LLM 调用的基础
- llm_config.py：封装 API Key 加载、客户端创建、CLI 配置编辑三大功能
- dicts/general.json：通用词典初始数据，步骤 3 中将完善管理接口
- .env.example：指导用户创建真实 .env 文件

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 2：实现 html_parser.py，解析 AO3 HTML 文件，拆分结构化数据（ParsedWork、TranslatableBlock）

---

## [2026-06-04 22:32] 步骤 2 完成：HTML 解析模块

### 执行的任务
- 完整实现 `html_parser.py`，支持解析 AO3 标准 HTML 文件
- 定义 `TranslatableBlock` 和 `ParsedWork` 两个数据类
- 实现标题、作者、标签（跳过 Stats）、摘要、前言备注、正文、尾注七个区域的解析
- 对各区域实现容错选择器，找不到元素时打印警告而不崩溃
- 空段落自动跳过（处理 AO3 常见 `<p> </p>` 占位行）
- 提供 `python html_parser.py <文件路径>` CLI 诊断入口
- 创建验证脚本 `_verify/step02_check_parser.py`（5 项检查，待用户运行后删除）

### 关键变更
- `html_parser.py`：核心解析模块，定义 `ParsedWork` / `TranslatableBlock` 数据结构，`parse_ao3_html()` 为对外主接口
- `_verify/step02_check_parser.py`：步骤 2 验证脚本，验证通过后需删除，不纳入 git

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 3：实现 `dict_manager.py`，提供词典读写 API 与独立 CLI 词典编辑器

---

## [2026-06-04 22:37] 步骤 3 完成：词典管理模块

### 执行的任务
- 完整实现 `dict_manager.py`，提供程序内调用 API 与独立 CLI 编辑器
- 程序内 API：`load_dict(path)`、`save_dict(path, data)`（原子替换写入）、`merge_dicts(general, ip)`（IP 优先级高于通用词典）、`list_dicts()`、`create_ip_dict(name, display_name)`
- CLI 编辑器（`python dict_manager.py`）：主菜单列出所有词典，支持选择词典后进入子菜单（查看/添加/删除词条、批量迁移），以及创建新 IP 词典
- 批量迁移实现复制/移动两种模式，冲突时询问用户是否覆盖，移动模式二次确认后清空源词典
- 原子写入：先写同目录临时文件，再通过 `os.replace` 原子替换，防止写入中途崩溃损坏词典
- 创建并运行 `_verify/step03_check_dict_manager.py`，10 项检查全部通过（0 错误）

### 关键变更
- `dict_manager.py`：核心词典管理模块，`load_dict` / `save_dict` / `merge_dicts` 为对外主 API，`run_cli()` 为 CLI 编辑器入口

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 4：实现 `term_extractor.py`，调用 LLM 提取术语，并实现 CLI 逐条确认流程

---

## [2026-06-04 22:45] 步骤 4 完成：术语提取 agent 与 CLI 确认流程

### 执行的任务
- 完整实现 `term_extractor.py`，包含术语提取、CLI 确认、整合三大功能
- `ExtractedTerm` 数据类：original / suggested_translation / note 三个字段
- `extract_terms(blocks, existing_terms, agent)`：调用 LLM 提取术语，自动分批（每批 ≤3000 字符），LLM 响应 JSON 解析带容错（支持纯数组、```json 代码块、前后有多余文字），已有词典词条自动跳过，大小写不敏感去重，指数退避重试（最多3次）
- `run_cli_confirm(terms)`：逐条 CLI 确认流程，支持 y（接受）/ n（跳过）/ s（跳过剩余），接受时可直接回车使用推荐译名或输入自定义译名
- `extract_and_confirm(blocks, existing_terms, agent)`：整合函数，供 main.py 调用，无术语时直接返回空字典
- `_extract_json_array(text)`：从 LLM 响应中健壮提取 JSON 数组
- `_split_into_batches(texts, char_limit)`：将文本列表分批，保证每批字符数不超限
- 模块顶层引用 `get_client`，确保 `patch("term_extractor.get_client")` 可用于单测
- 提供 `python term_extractor.py <html_path>` CLI 快速测试入口
- 创建并运行 `_verify/step04_check_term_extractor.py`，36 项检查全部通过（0 错误）

### 关键变更
- `term_extractor.py`：核心模块，`extract_terms` / `run_cli_confirm` / `extract_and_confirm` 为对外主 API

### 遇到的问题及解决方案
- `patch("term_extractor.get_client")` 失败：因 `get_client` 通过函数内局部 import 导入，不在模块命名空间中。解决方案：改为模块顶层 import，失败时赋值 None，调用时再检查。

### 下一步计划
- 步骤 5：实现 `translator.py`，基于合并词典对文本块分批翻译，带词典约束校验与指数退避重试

---
