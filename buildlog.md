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

## [2026-06-04 23:01] 修复：验证脚本 sys.path 配置缺失导致 No module named 'translator'

### 问题描述
- 现象：运行 `_verify/step05_check_translator.py` 时报错 `ModuleNotFoundError: No module named 'translator'`，无法完成步骤 5 的验证
- 影响范围：步骤 5 验证流程；translator.py 本身功能不受影响

### 根本原因
验证脚本 `_verify/step05_check_translator.py` 未在脚本顶部添加 `sys.path` 配置，导致 Python 解释器在 `_verify/` 子目录中运行时找不到项目根目录下的 `translator` 模块。其他验证脚本（step01~step04）存在相同的路径处理方式，但本脚本遗漏了该配置。

### 修复方案
在 `_verify/step05_check_translator.py` 顶部添加以下代码，将项目根目录插入 `sys.path`：
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
```
此方案与其他验证脚本保持一致，不修改 translator.py 或任何生产代码。

### 变更文件
- `_verify/step05_check_translator.py`：顶部添加 sys.path 配置，使脚本能正确导入项目根目录模块

### 验证方法
运行 `python _verify/step05_check_translator.py`，全部检查项通过（用户已确认验证通过）

---

## [2026-06-04 23:06] 步骤 6 完成：润色 agent（polisher.py）

### 执行的任务
- 完整实现 `polisher.py`，提供 `polish_blocks` 和 `polish_work` 两个公开接口
- 实现与翻译模块相同的分批策略（每批 10 段，`BATCH_SIZE=10`）
- 润色结果直接覆盖 `translation` 字段
- 支持 `skip_polish=True` 参数跳过润色（对应 `--skip-polish` CLI 参数）
- 修复逻辑顺序：先检查是否有可润色段落，再初始化 LLM 客户端（全无译文时不调用 API）
- 带指数退避重试（最多 3 次），分隔符不匹配时自动降级为逐段润色
- 创建验证脚本 `_verify/step06_check_polisher.py`（7 类检查共 13 项，使用 mock 客户端，无需真实 API）
- 验证全部通过（13/13）

### 关键变更
- `polisher.py`：润色模块，`polish_work()` 为对外主接口，`skip_polish=True` 可完全跳过
- `_verify/step06_check_polisher.py`：步骤 6 验证脚本，验证通过后需删除，不纳入 git

### 遇到的问题及解决方案
1. 验证脚本中 `nonlocal` 用于模块级变量导致 SyntaxError，改用列表（可变对象）规避。
2. `polish_blocks` 原先在检查"是否有可润色段落"之前就调用 `get_client`，导致全无译文时 mock patch 无法拦截而报错。调整顺序：先过滤可润色块，若为空直接返回，再获取客户端。

### 下一步计划
- 步骤 7：实现 `output_writer.py`，支持 txt / Markdown / docx 三种输出格式，并在 txt 输出后插入中途暂停等待用户精校

---

## [2026-06-04 23:59] 步骤 7 完成：输出模块（txt / Markdown / docx）

### 执行的任务
- 完整实现 `output_writer.py`，提供 txt / Markdown / docx 三种输出格式
- 实现 `_safe_stem()`：将输入文件名主干强制转换为纯 ASCII，中文等非 ASCII 字符全部移除，结果为空时回退为 `work`，从根源消除 Windows 编码风险
- 实现 `get_output_paths()`：输出文件与输入文件同目录，文件名格式为 `{ASCII主干}_translated.{ext}`
- 实现 `write_txt()`：仅输出正文译文，段落间空行分隔，强制 UTF-8 编码写入
- 实现 `pause_for_proofread()`：中途暂停等待用户精校 txt，读取精校结果后返回段落列表
- 实现 `write_markdown()`：输出包含标签、摘要、前言备注、精校正文、尾注的完整结构，支持传入精校段落列表覆盖正文
- 实现 `write_docx()`：通过 `subprocess` 调用 pandoc，使用 `cwd=文件所在目录 + 纯文件名` 规避 Windows 路径编码问题；pandoc 未安装时输出明确提示
- 实现 `write_all()`：串联完整三步输出流程，含段落数不匹配时的用户确认逻辑；`skip_pause=True` 可跳过精校暂停（用于测试）
- 创建验证脚本 `_verify/step07_check_output_writer.py`（8 类检查共 15 项，使用临时目录，无副作用），验证全部通过

### 关键变更
- `output_writer.py`：输出模块，`write_all()` 为对外主接口，文件名强制 ASCII 安全
- `_verify/step07_check_output_writer.py`：步骤 7 验证脚本，验证通过后已删除，不纳入 git

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 8：实现 `main.py`，将所有模块串联为完整 CLI 工具，支持参数解析、断点续传、进度提示

---

## [2026-06-05 00:29] 步骤 8 完成：主流程入口与整体集成（main.py）

### 执行的任务
- 完整实现 `main.py`，将 html_parser / dict_manager / term_extractor / translator / polisher / output_writer 六个模块串联为完整 CLI 工具
- 实现 8 步进度编号（含 --skip-* 参数时自动缩减总步骤数）
- 实现词典自动推断：未指定 `--ip-dict` 时按输入文件名的 ASCII 词干在 `dicts/ip/` 下查找或新建
- 实现断点续传：正文翻译使用 `{stem}_progress.json` 持久化，完成后自动清理
- 实现漏译校验：翻译完成后调用 `verify_terms()` 打印警告
- 实现完成摘要：输出三个文件路径、正文段落数、使用术语数
- 创建验证脚本 `_verify/step08_check_main.py`（5 类检查共 12 项，mock LLM 调用），全部通过后已删除

### 关键变更
- `main.py`：主流程入口，`main()` 为对外接口，`python main.py <html> [选项]` 可直接使用

### 遇到的问题及解决方案
1. **`global (...)` 括号语法错误**：Python 的 `global` 语句不支持括号跨行写法，改为多条 `global` 语句后仍存在根本问题——`_import_modules()` 在 `main()` 内重新绑定模块名，覆盖了测试 mock。最终删除延迟导入函数，改为顶层直接 `import`，mock 可正常拦截。
2. **测试 HTML 标题选择器不匹配**：验证脚本的 `TEST_HTML` 缺少 `<div class="meta">` 包装，`html_parser.py` 使用 `.meta h1` 选择器故无法解析标题。在测试 HTML 中补充该包装后断言通过。

### 下一步计划
- ✅ 所有构建步骤已全部完成（步骤 1-8）

---
