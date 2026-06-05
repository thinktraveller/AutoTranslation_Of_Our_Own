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

## [2026-06-05 00:51] 步骤 9 完成：子模块迁移至 src/ 目录

### 执行的任务
- 创建 `src/` 目录及 `src/__init__.py`
- `git mv` 将 7 个业务子模块从根目录迁移至 `src/`（html_parser / term_extractor / translator / polisher / output_writer / llm_config / dict_manager）
- 修复 src/ 内 4 个模块的跨模块 import（改为相对导入 `.llm_config`、`.html_parser`）
- 修复 `src/llm_config.py`：`Path(__file__).parent` → `.parent.parent`（PROJECT_ROOT 重新指向项目根）
- 修复 `src/dict_manager.py`：同上修复 DICTS_DIR、IP_DIR 及 relative_to 路径
- 更新 `main.py` 全部 import 为 `from src.xxx import`
- 在根目录创建 `llm_config.py` 和 `dict_manager.py` 转发 stub，保持 `python llm_config.py` / `python dict_manager.py` 向下兼容

### 关键变更
- `src/__init__.py`：新建，标记 src 为 Python 包
- `src/html_parser.py` / `src/term_extractor.py` / `src/translator.py` / `src/polisher.py` / `src/output_writer.py` / `src/llm_config.py` / `src/dict_manager.py`：7 个子模块迁入，含 import 与路径修复
- `main.py`：6 处 import 改为 `from src.xxx import`
- `llm_config.py`（根目录）：转发 stub，`if __name__ == '__main__': run_cli()`
- `dict_manager.py`（根目录）：转发 stub，同上

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 10：为 main.py 添加交互式输入模式（无参数时引导用户逐步输入 HTML 路径及选项）

---

## [2026-06-05 00:54] 步骤 10 完成：main.py 交互式输入模式

### 执行的任务
- 在 `main.py` 中新增 `_interactive_input()` 函数：无参数启动时引导用户逐步输入 HTML 路径及翻译选项
- 在 `main()` 入口添加检测逻辑：`len(sys.argv) == 1` 时自动切换为交互模式
- 更新模块 docstring，说明交互式与 CLI 两种启动方式
- 交互模式支持：路径无效循环重试、引号路径去除、等价命令回显、EOFError 安全退出

### 关键变更
- `main.py`：新增 `_interactive_input()` 函数（约 40 行），`main()` 入口添加 2 行触发逻辑

### 遇到的问题及解决方案
- 无

### 下一步计划
- ✅ 步骤 9-10 全部完成，准备执行端到端终验

---

## [2026-06-05 00:56] 🎉 项目构建全部完成（步骤 1-10）

### 完成情况
- 所有步骤（1-10）已执行完毕，端到端终验（v2）通过
- 终验覆盖：src/ 包结构完整性、全模块导入、交互式输入模式、main() 完整翻译流程（mock LLM）、CLI 模式不触发交互（回归验证）

### 下一步计划
- ✅ 构建已全部完成，无待执行步骤

---

## [2026-06-05 09:35] 步骤 11 完成：Bug 修复与优化计划（B-1 至 B-7、O-1 至 O-3）

### 执行的任务

**Bug 修复（P0）**
- B-1：`--source-lang` 参数现已实际传递给 term_extractor / translator / polisher 三个 agent 的提示词，提示词中的语言描述由硬编码「英文」改为动态插值（`{source_lang}`）；交互式启动流程增加源语言询问步骤
- B-2：术语确认流程新增「仅本次使用（t）」选项，选 t 的术语存入临时 `session_terms` 字典，在本次翻译提示词中生效但不写入词典文件；`extract_and_confirm()` 返回值从 `dict` 扩展为 `tuple[dict, dict]`，`main.py` 同步更新调用逻辑

**Bug 修复（P1 输出质量）**
- B-5：HTML 解析时新增对 `Language` 字段的过滤（与 `Stats` 并列），Language dd 不再出现在翻译后的 Markdown 和 docx 中
- B-6：`ParsedWork` 新增 `source_url` 字段；`html_parser.py` 解析 `<link rel="canonical">` 或页面内 AO3 作品链接；`output_writer.py` 在 Markdown 末尾追加「原文链接：」段落
- B-7：`output_writer.py` 中二级标题 `## 标签信息` 改为 `## Tags`，`## 摘要` 改为 `## Summary`

**Bug 修复（P1 流程完整性）**
- B-3：`output_writer.py` 新增 `pause_before_docx()` 函数；`write_all()` 在 Markdown 生成后、pandoc 转换前插入第二次暂停，供用户检视 Markdown
- B-4：`write_docx()` 新增 `reference_doc` 参数，支持 `--reference-doc` 模板；`main.py` 新增 `--docx-template PATH` CLI 参数；交互式启动新增 docx 模板询问步骤

**优化项（P2/P3）**
- O-3：`dict_manager.py` 的删除词条界面改进，展示带序号的词条列表，支持输入纯数字序号或原文文本两种方式删除，向下兼容
- O-1：`html_parser.py` 新增章节边界解析（多章作品按 `div[id^='chapter-']` 拆分，单章回退为 `[body]`），`ParsedWork` 新增 `chapters` 字段；`polisher.py` 实现三种批次模式（full/chapter/paragraph），由 `config.json` 的 `agents.polisher.polish_batch_mode` 控制；`config.json` 新增 `polish_batch_mode` 和 `polish_context_token_limit` 字段
- O-2：`llm_config.py` 新增 `_edit_agent_prompt()` 函数，CLI 菜单新增「查看/编辑 Agent 提示词」选项（选项 4），支持多行输入/删除，保存到 `config.json` 的 `agents.<name>.system_prompt`；三个 agent 模块（term_extractor / translator / polisher）均优先读取 config 中的 `system_prompt` 字段，回退到模块内置默认值；`get_agent_config()` 修改为返回完整 agent 配置（含所有自定义字段）

### 关键变更
- `src/html_parser.py`：新增 `source_url` 字段、`chapters` 字段、Language 过滤、章节边界解析
- `src/output_writer.py`：B-3 第二次暂停、B-4 reference_doc 支持、B-6 原文链接、B-7 章节标题
- `src/term_extractor.py`：B-1 source_lang 参数、B-2 session_terms、O-2 自定义提示词支持
- `src/translator.py`：B-1 source_lang 参数、O-2 自定义提示词支持
- `src/polisher.py`：B-1 source_lang 参数、O-1 三种批次模式、O-2 自定义提示词支持
- `src/dict_manager.py`：O-3 序号删除支持
- `src/llm_config.py`：O-2 _edit_agent_prompt 菜单、get_agent_config 返回完整字段
- `main.py`：B-1/B-2/B-4 参数传递更新、交互式输入新增步骤
- `config.json`：O-1 新增 polish_batch_mode 和 polish_context_token_limit 字段

### 遇到的问题及解决方案
- B-2 引入新返回值后 main.py 原有 else 分支产生双重 else，已合并为单一 else 分支

### 下一步计划
- ✅ 步骤 11 全部子项（B-1 至 B-7、O-1 至 O-3）已完成，构建全部结束

---

## [2026-06-05 09:50] 修复：三处步骤 11 引入的遗留 Bug

### 问题描述

**Bug A：term_extractor.py CLI __main__ 块 AttributeError 崩溃**
- 现象：直接运行 `python src/term_extractor.py <html>` 时，若提取到术语进入确认流程后报 `AttributeError: 'tuple' object has no attribute 'items'`
- 影响范围：CLI 直接测试入口；通过 main.py 调用的正常流程不受影响

**Bug B：llm_config.py _edit_agent() 编辑 agent 时丢失自定义字段**
- 现象：在配置编辑器（选项 3）中修改 polisher 的模型或温度后，`polish_batch_mode`、`polish_context_token_limit`、`system_prompt` 等自定义字段被清空
- 影响范围：所有通过 CLI 编辑器修改过 agent 配置的场景；首次创建 agent 不受影响

**Bug C：dicts/general.json 新增词条未提交且缺少末尾换行**
- 现象：F/F → 女/女 和 Creator Chose Not To Use Archive Warnings → 作者选择不声明雷点 两条词条已添加到文件但未纳入版本控制；文件末尾缺少换行符
- 影响范围：词典内容可用但版本不一致

### 根本原因

**Bug A**：步骤 11 的 B-2 修复将 `extract_and_confirm()` 返回值从 `dict` 改为 `tuple[dict, dict]`，但 `__main__` 演示块仍按旧接口接收单个返回值，导致后续的 `.items()` 调用作用于 tuple 对象。

**Bug B**：`_edit_agent()` 函数直接用 `{"provider": ..., "model": ..., "temperature": ...}` 字典覆盖整个 agent 条目，而不是在现有条目上更新，因此凡不在这三个字段中的自定义键（如 `polish_batch_mode`）全部丢失。

**Bug C**：步骤 11 在 general.json 中补充了两条新术语，但未提交；同时 save_dict 函数使用 json.dump 写入，末尾不带换行，与文件既有格式不一致。

### 修复方案

**Bug A**：将 `confirmed = extract_and_confirm(...)` 改为 `confirmed, session_terms = extract_and_confirm(...)`，并在演示块末尾同时打印 `session_terms` 内容。

**Bug B**：`_edit_agent()` 中先获取 `existing_agent = config["agents"].get(name, {})`，再以 `{**existing_agent}` 为基础更新三个基础字段，保留所有其他自定义键不变。

**Bug C**：在 general.json 末尾补充换行符，并将两条新术语一并提交到版本控制。

### 变更文件
- `src/term_extractor.py`：`__main__` 块改用元组拆包接收 `extract_and_confirm` 返回值，补充 session_terms 打印
- `src/llm_config.py`：`_edit_agent()` 改为在现有配置基础上更新，保留自定义字段
- `dicts/general.json`：补充末尾换行符，纳入已有的两条新术语

### 验证方法
- Bug A：`python src/term_extractor.py test/Tease_Test_Taste.html` 可正常运行至确认界面，无 AttributeError
- Bug B：在 llm_config CLI 编辑 polisher agent 的温度后，config.json 中 `polish_batch_mode` 字段仍存在
- Bug C：`git status` 显示 dicts/general.json 已提交，文件末尾有换行符

---

## [2026-06-05] 修复：_interactive_input() 三处交互提示问题

### 问题描述

1. **`(y/N)` 提示不直观**：跳过术语提取、跳过润色、禁用通用词典三处提示均使用 `(y/N)` 括号格式，不够明确，用户难以快速判断默认行为。
2. **docx 模板默认路径缺失**：`markdown-to-docx/template.docx` 已存在，但交互模式提示为"回车跳过，不使用模板"，未自动检测该默认模板，导致用户每次均需手动输入路径。
3. **IP 词典选择为自由输入**：`dicts/ip/` 目录下已有词典文件时，仍提示用户手动输入路径，未扫描列出可选项，操作繁琐且易出错。

### 修复方案

1. **`(y/N)` → 方括号明确提示**：将三处提示改为 `[y 跳过 / 回车继续]`、`[y 跳过 / 回车执行]`、`[y 禁用 / 回车启用]` 形式，默认行为一目了然。
2. **docx 模板自动检测**：交互模式中检测 `Path(__file__).parent / 'markdown-to-docx' / 'template.docx'` 是否存在；存在时打印路径并询问"回车使用 / n 跳过 / 输入其他路径"，不存在时回退为自由输入。
3. **IP 词典编号选择**：交互模式中扫描 `dicts/ip/*.json`；若找到文件则展示带编号的列表（含 `[0] 自动推断` 选项），用户输入编号即可；若目录为空则回退为自由输入，保持向下兼容。

### 变更文件
- `main.py`：`_interactive_input()` 函数，第 159-213 行重写三处交互步骤

### 下一步计划
- ✅ 本轮修复完成

---
