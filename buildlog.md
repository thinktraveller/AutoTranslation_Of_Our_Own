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

## [2026-06-05 11:06] 修复：verify_terms() \b 不兼容非 ASCII 字符 & main.py Pylance reconfigure 类型报错

### 问题描述
- **问题 1**：`verify_terms()` 对所有词典原文统一使用 `\b` 单词边界，导致对日文、韩文、法文等全非 ASCII 词汇的漏译校验永远无法命中（`\b` 依赖 ASCII `\w` 定义，两个非 ASCII 字符之间不存在词边界），校验结果静默失效。
- **问题 2 & 3**：`main.py` 第 33-34 行直接在 `sys.stdout` / `sys.stderr` 上调用 `.reconfigure()`，Pylance 报「属性 "reconfigure" 未知」——`sys.stdout` 的静态类型为 `TextIO`（`typing` 模块），该接口未声明 `reconfigure`，运行时实际类型 `io.TextIOWrapper` 有该方法但静态检查不认。
- 影响范围：问题 1 影响所有非英文原文词典的漏译校验；问题 2 & 3 影响 Pylance 类型检查，运行时无影响。

### 根本原因
- **问题 1**：`re` 的 `\b` 边界基于 ASCII 字符集的 `\w` 定义，无法识别 Unicode 非 ASCII 字符之间的边界，对全非 ASCII 词汇的搜索模式形同 `.*\b.*`，永远不匹配。
- **问题 2 & 3**：`typing.TextIO` 是最小化 IO 协议接口，不包含 `io.TextIOWrapper` 特有的 `reconfigure` 方法，Pylance 按静态类型检查时报告属性缺失。

### 修复方案
- **问题 1**：在 `verify_terms()` 中，对 `orig` 做字符检测：若去除空格后全部为非 ASCII 字符（`ord(c) > 127`），则不加 `\b` 边界，直接使用 `re.escape(orig_lower)`；含 ASCII 字符的词汇保留原 `\b` 边界防止误报。
- **问题 2 & 3**：在 `main.py` 新增 `import io` 和 `from typing import cast`；将 `try/except` 块改为 `hasattr` 守卫（`if hasattr(sys.stdout, 'reconfigure')`），并通过 `cast(io.TextIOWrapper, sys.stdout).reconfigure(...)` 显式告知 Pylance 实际类型，消除静态报错，运行时行为不变。

### 变更文件
- `src/translator.py`：`verify_terms()` 函数，第 580-582 行，添加非 ASCII 词汇的 `\b` 绕过逻辑
- `main.py`：新增 `import io` 和 `from typing import cast`，Windows UTF-8 块改为 `hasattr` 守卫 + `cast` 调用

### 验证方法
- `python -c "import ast; ast.parse(open('src/translator.py', encoding='utf-8').read())"` 无报错
- `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read())"` 无报错
- 逻辑验证：`all(ord(c) > 127 for c in '日文词'.replace(' ', ''))` 为 True，走无边界路径；`all(ord(c) > 127 for c in 'Harry'.replace(' ', ''))` 为 False，走 `\b` 路径

---

## [2026-06-05] 步骤 12 完成：调用日志、超时报错、断点续翻、批次心跳

### 执行的任务

**子项 12-1：完整调用日志（src/llm_logger.py，JSONL 格式）**
- 新建 `src/llm_logger.py`，提供 `log_call()` / `get_recent_entries()` / `get_log_path()` 三个公开接口
- 日志文件：项目根目录 `llm_calls.jsonl`，每次 LLM 调用追加一条 JSON 记录
- 记录字段：timestamp / phase / agent / model / batch_index / total_batches / input_chars / output_chars / elapsed_s / success / error / log_line
- `log_line` 字段记录本条日志的行号（1-based），失败时可直接在错误提示中引用
- 线程安全：内置 `_write_lock` 防止心跳线程与主线程并发写入冲突
- 写入失败不阻断主流程（仅打印警告）
- `llm_calls.jsonl` 加入 `.gitignore`，不纳入版本控制

**子项 12-2：超时报错（timeout 注入 + 清晰提示 + 打印日志行号 + 续翻说明）**
- `translator.py`、`polisher.py`、`term_extractor.py` 的 `_call_llm` 均已从 `agent_cfg.timeout` 读取超时秒数（默认 120）
- 超时异常检测：匹配异常类型名（APITimeoutError / Timeout / ConnectTimeout / ReadTimeout）及消息中的 "timeout" / "timed out"
- 超时时打印友好提示，含配置项位置（config.json agents.<name>.timeout）和"进度已自动保存，将从断点继续"说明
- 失败时同时打印日志行号（`llm_calls.jsonl 第 N 行`），便于排查
- 每次调用（成功/失败）均写入 JSONL 日志，并在控制台打印日志行号

**子项 12-3：断点续翻（统一 .translation_checkpoint.json，覆盖四阶段）**
- `main.py` 引入统一检查点 `.translation_checkpoint.json`（与输入 HTML 同目录）
- 检查点结构：`{source_file, phases: {non_body: {done, translations}, body: {done, translations}, polish: {done}}}`
- 四个阶段均有独立的完成标记（`done: bool`）和段落数据（`translations: {block_id: text}`）
- 每阶段完成后立即写入检查点；重新运行时自动恢复所有阶段的已完成译文
- 若检查点 `source_file` 与当前输入文件不符，自动丢弃旧检查点（避免不同文件混用）
- 翻译全部完成后（输出文件写出后）自动删除检查点
- 新增辅助函数：`_checkpoint_path()` / `_load_checkpoint()` / `_save_checkpoint()` / `_blocks_to_translations()` / `_restore_from_translations()`
- 废弃旧的 `{stem}_progress.json`，统一使用新检查点（`.gitignore` 同步更新）
- `KeyboardInterrupt` 在各翻译阶段均向上传播，由信号处理器统一接管
- Ctrl+C 信号处理器（`_sigint_handler`）：捕获 SIGINT → 保存当前进度到检查点 → 打印续翻命令 → 退出码 130

**子项 12-4：批次进度心跳（已在前序步骤实现，本步骤完善）**
- `_HeartbeatTimer` 已在 translator / polisher / term_extractor 三个模块中实现并覆盖所有 LLM 调用
- 每 60 秒打印等待提示，包含阶段名和已等待时长（"[等待] XX仍在进行，已等待 Xm Ys..."）
- 调用完成时打印耗时（"[完成] XX完成（耗时 Xs）"）
- term_extractor 本次补充心跳（之前的 `_call_llm_for_terms` 无心跳），现已完整覆盖

### 关键变更
- `src/llm_logger.py`：新建，LLM 调用日志模块（JSONL 格式）
- `src/translator.py`：集成 log_call，超时错误清晰提示，注入 _agent_name 到 agent_cfg
- `src/polisher.py`：集成 log_call，超时错误清晰提示，注入 _agent_name 到 agent_cfg
- `src/term_extractor.py`：集成 log_call，超时错误清晰提示，补充心跳计时器，读取 timeout 配置
- `main.py`：引入 json/signal 模块，新增统一检查点四阶段管理，Ctrl+C 捕获与保存，旧 progress_path 移除
- `.gitignore`：新增 `.translation_checkpoint.json` 和 `llm_calls.jsonl`

### 验证方法
- 语法检查：全部五个文件 ast.parse() 通过
- 功能测试：log_call 写入/读取、_blocks_to_translations/_restore_from_translations、_save_checkpoint/_load_checkpoint 全部通过
- 导入测试：from src.llm_logger import ... 、import main 均无报错

### 下一步计划
- 步骤 12 全部子项完成

---

## 修复记录 2026-06-05 11:16

### Bug 修复

**B-1：`verify_terms()` `\b` 不兼容非 ASCII 字符**
- 文件：`src/translator.py`
- 问题：`verify_terms()` 对词典键统一使用 `\b` 单词边界正则，导致全非 ASCII 字符（如中文、日文词条）无法匹配，术语校验失效
- 修复：对全非 ASCII 字符的词典键不使用 `\b` 边界，改用子串匹配（`in` 运算符或无边界正则），ASCII 词条保持 `\b` 匹配不变

**B-2：`main.py` 第 33 行 Pylance `reconfigure` 属性报错（`sys.stdout`）**
- 文件：`main.py`
- 问题：`sys.stdout.reconfigure(...)` 调用在静态类型检查（Pylance）下报错，因为 `sys.stdout` 类型为 `TextIO`，该接口不含 `reconfigure` 方法
- 修复：新增 `import io` 和 `from typing import cast`，用 `hasattr(sys.stdout, "reconfigure")` 守卫，配合 `cast(io.TextIOWrapper, sys.stdout).reconfigure(...)` 消除静态类型报错

**B-3：`main.py` 第 34 行 Pylance `reconfigure` 属性报错（`sys.stderr`）**
- 文件：`main.py`
- 问题：同 B-2，`sys.stderr.reconfigure(...)` 存在相同静态类型问题
- 修复：同 B-2，使用 `hasattr` 守卫配合 `cast(io.TextIOWrapper, sys.stderr).reconfigure(...)` 消除报错

### 关键变更
- `src/translator.py`：`verify_terms()` 增加 ASCII/非 ASCII 分支判断，全非 ASCII 键改用子串匹配
- `main.py`：新增 `import io`、`from typing import cast`，对 `sys.stdout` 和 `sys.stderr` 的 `reconfigure` 调用加 `hasattr` 守卫与 `cast` 类型断言

### 验证方法
- 静态检查：Pylance 对 `main.py` 第 33、34 行不再报 `reconfigure` 属性错误
- 功能验证：含中文/日文词条的词典在 `verify_terms()` 中可正常命中，ASCII 词条行为不变

---

## [2026-06-05] Bug 修复：html_parser.py 作者前缀与尾注容错

### 修复的 Bug

**Bug 1 — 作者名含 "by" 前缀（第 148-149 行）**
- 问题：`div.byline` 的文本内容通常以 "by " 开头（如 "by AuthorName"），直接提取后作者名包含冗余前缀，影响元信息展示
- 修复：提取文本后追加 `re.sub(r'^by\s+', '', author, flags=re.IGNORECASE)`，去除开头的 "by"（大小写均可）

**Bug 2 — 尾注解析无容错降级（第 241-246 行）**
- 问题：尾注区域只硬查 `blockquote.userstuff`，部分 AO3 页面使用 `div.userstuff` 或无该子元素，导致尾注静默丢失
- 修复：找不到 `blockquote.userstuff` 时，依次尝试 `div.userstuff`，仍无则以整个 `#endnotes` 作为容器调用 `_blocks_from_userstuff()`，与正文解析策略保持一致

### 关键变更
- `src/html_parser.py`：第 150 行新增 `re.sub` 去除 "by" 前缀；第 247-250 行新增两级降级容错逻辑

### 验证方法
- 代码审查：`re` 模块已在第 9 行导入，两处修改语法正确，逻辑覆盖完整

---

## [2026-06-05 11:47] 步骤 13 完成：模型方案（Profile）系统

### 执行的任务
- **config.json**：追加 `default_profile` 字段（值为 `"balanced"`）和顶层 `profiles` 字段，内置 `fast` / `balanced` / `quality` 三个预设方案；同时补充 `openai` 提供商配置；旧版 `agents` 字段原样保留（向下兼容）
- **`src/llm_config.py`**：
  - 新增 `get_profile_config(profile_name)` 函数，实现四级优先级（显式参数 → default_profile → agents → 硬编码兜底），返回深拷贝防止副作用
  - 更新 `get_client(agent_name, profile_config=None)` 签名，`profile_config` 不为 None 时优先从方案中取 agent 配置并合并提供商的 base_url/api_key_env，否则沿用旧逻辑（向下兼容）
  - 新增 Profile 管理子菜单（选项 5）：5-1 查看所有方案 / 5-2 新建方案 / 5-3 编辑方案 / 5-4 删除方案（内置不可删，并联动清空 default_profile）/ 5-5 设为默认方案；旧版菜单「删除提供商」从选项 5 调整为选项 6，「退出」从选项 6 调整为选项 7
  - `import copy` 新增，用于深拷贝
- **`main.py`**：
  - 新增 `--profile NAME` CLI 参数
  - `main()` 入口解析参数后立即调用 `get_profile_config(args.profile)` 加载方案配置，失败时静默降级为 None
  - 将 `profile_cfg` 透传给三处 agent 调用：`extract_and_confirm`、`translate_work`（非正文区和正文两处）、`polish_work`
  - `_interactive_input()` 在 HTML 路径输入之后、源语言之前插入方案选择菜单（动态列出内置方案 + config.json 中的自定义方案）
- **`src/term_extractor.py`**：`extract_terms()` 和 `extract_and_confirm()` 签名新增 `profile` 参数，透传至 `get_client(profile_config=profile)`
- **`src/translator.py`**：`translate_blocks()` 和 `translate_work()` 签名新增 `profile` 参数，透传至 `get_client(profile_config=profile)`
- **`src/polisher.py`**：`polish_blocks()` 和 `polish_work()` 签名新增 `profile` 参数，透传至 `get_client(profile_config=profile)`；读取 `polish_batch_mode` 等字段时优先读 profile 的 polisher 配置，再回退到 `get_agent_config`
- **`src/dict_manager.py`**：顺带提交之前遗留的微小改动（提示文本"原文（英文术语）"→"原文"）

### 关键变更
- `config.json`：新增 `default_profile` / `profiles`（fast/balanced/quality）/ openai 提供商
- `src/llm_config.py`：新增 `get_profile_config()`、更新 `get_client()` 签名、新增 Profile 管理菜单（选项 5）
- `main.py`：新增 `--profile` 参数、交互式方案选择、`profile_cfg` 传递给三个 agent 调用
- `src/term_extractor.py` / `src/translator.py` / `src/polisher.py`：各新增 `profile` 参数并透传

### 遇到的问题及解决方案
- 无

### 下一步计划
- 步骤 13 全部完成，构建全部结束

---

## [2026-06-05 15:13] 步骤 14 完成：输出文件目录规范

### 执行的任务
- 修改 `src/output_writer.py` 的 `get_output_paths()` 函数，新增 `output_dir` 参数：
  - `output_dir=None`（默认）时，在 HTML 文件同级目录下创建以文件名主干命名的子文件夹（如 `novels/MyFic.html` → 输出到 `novels/MyFic/`）
  - `output_dir` 指定时，输出到该目录（自动 `mkdir(parents=True, exist_ok=True)`）
- 修改 `src/output_writer.py` 的 `write_all()` 函数，新增 `output_dir` 参数并透传给 `get_output_paths()`
- 在 `main.py` 的 `_parse_args()` 中新增 `--output-dir PATH` CLI 参数
- 在 `main.py` 的主流程中将 `args.output_dir` 传递给 `write_all(output_dir=output_dir)`
- 在 `main.py` 的 `_interactive_input()` 末尾（步骤 9）新增输出目录询问，回车跳过使用默认
- 更新 `main.py` 顶部 docstring，补充 `--output-dir` 参数说明
- 创建验证脚本 `_verify/step14_check_output_dir.py`（6 类 11 项检查），全部通过后已删除

### 关键变更
- `src/output_writer.py`：`get_output_paths()` 新增 `output_dir` 参数，默认输出至同名子文件夹并自动创建；`write_all()` 新增 `output_dir` 参数
- `main.py`：新增 `--output-dir` CLI 参数，主流程传参，交互式流程新增步骤 9 询问

### 遇到的问题及解决方案
- 无

### 验证结果
- 验证脚本 `_verify/step14_check_output_dir.py` 共 6 类 11 项检查，全部通过（用户已确认）
- 验证通过后脚本已删除

### 下一步计划
- 步骤 15：日志文件夹结构与三处断点续传

---

## [2026-06-05 15:21] 步骤 15 完成：日志文件夹结构与三处断点续传

### 执行的任务

**15-A 日志文件夹结构**
- 新增 `logs/` 根日志文件夹（含 `.gitkeep`，目录本身纳入版本控制，内容被 `.gitignore` 排除）
- 在 `main.py` 入口新增 `_create_task_log_dir()` 函数，每次任务创建 `logs/{词干}_{时间戳}/` 子文件夹
- 将 `_checkpoint_path()` 修改为接受 `log_dir` 参数，将 progress.json 放在子日志文件夹内（原 `.translation_checkpoint.json` 同目录兼容路径保留为回退）
- 更新 `.gitignore`，新增 `logs/*` / `!logs/.gitkeep` 规则

**15-B 任务状态文件**
- 新增 `_build_initial_task_state()` 函数，构造含 version/html_path/html_stem/started_at/interrupted_at/breakpoint/args/cache 字段的初始状态
- 新增 `_save_task_state()` 函数，使用原子写入（先写 `.tmp` 再重命名）防止中断时文件损坏
- `main()` 入口初始化后立即写入 `logs/{子目录}/task_state.json`；任务正常完成后将 `breakpoint` 清空为 `null`

**15-C 三处断点实现**
- 新增 `_breakpoint_prompt(label, breakpoint_key, task_state, log_dir)` 函数：显示 `[Enter]` 继续 / `[s]` 保存退出两个选项；选 `s` 时原子写入 task_state 后返回 `False`
- 将原来的 `write_all()` 整合调用展开为逐步调用（`write_txt` / `pause_for_proofread` / `write_markdown` / `write_docx`）
- 在术语提取步骤之后插入断点 1（`after_term_confirm`）
- 在 txt 精校暂停之后、Markdown 生成之前插入断点 2（`after_txt_polish`）
- 在 Markdown 生成之后、docx 生成之前插入断点 3（`after_md_review`）
- 各断点恢复时正确跳过已完成阶段（如从 `after_md_review` 恢复时跳过写 txt / 精校 / 写 md）

**15-D 启动时扫描未完成任务**
- 新增 `_find_incomplete_tasks()` 函数：扫描 `logs/`，返回所有 `breakpoint != null` 的未完成任务（最新在前）
- 新增 `_prompt_resume()` 函数：列出任务（含文件名、中断时间、断点位置），支持数字选择恢复、`d<序号>` 删除（`shutil.rmtree`）、回车忽略
- `main()` 入口在交互模式下先调用扫描，选择恢复时从保存的 `args` 字段重建 argv，跳过 `_interactive_input()`，直接从断点处继续
- 新增导入：`shutil`、`datetime`

### 关键变更
- `main.py`：新增 `_create_task_log_dir` / `_save_task_state` / `_build_initial_task_state` / `_breakpoint_prompt` / `_find_incomplete_tasks` / `_prompt_resume` 六个函数；`_checkpoint_path` 新增 `log_dir` 参数；`main()` 流程大幅扩展断点逻辑；`write_all` 调用改为逐步展开
- `.gitignore`：新增 `logs/*` / `!logs/.gitkeep` 规则
- `logs/.gitkeep`：新建，确保 logs 目录被 git 追踪

### 遇到的问题及解决方案
- `from src.output_writer import write_all` 改为导入各子函数（`write_txt` / `pause_for_proofread` / `write_markdown` / `pause_before_docx` / `write_docx`），`output_writer.py` 本身无需修改
- 从 `after_txt_polish` 恢复时需跳过精校暂停并读取已精校的 txt 内容回填 `work.body`，避免二次要求用户精校

### 下一步计划
- 步骤 15 全部完成，构建全部结束

---

## [2026-06-05 16:03] 修复：交互式启动方案菜单硬编码导致已删除方案仍显示

### 问题描述
- 现象：运行 `python main.py`（无参数，进入交互式模式）时，方案选择菜单始终显示 fast / balanced / quality 三个硬编码选项，即使用户已通过配置编辑器将这三个内置方案删除（写入 `deleted_profiles`）。实际 config.json 中只有 `r18` 和 `general` 两个自定义方案可用，但菜单无法选到它们（两个自定义方案仅作为"额外"选项被追加到固定的三个内置选项之后）。
- 影响范围：交互式启动时所有用户均受影响；选择已删除的内置方案会导致运行时使用硬编码兜底方案而非用户预期的实际可用方案。

### 根本原因
`_interactive_input()` 中的方案选择逻辑（原第 403-436 行）：
1. 固定打印三条 `print()` 语句展示 fast / balanced / quality，不受 `deleted_profiles` 约束
2. `_custom_profiles` 的过滤条件是 `k not in {"fast", "balanced", "quality"}`，仅把不在内置名集合中的方案追加显示，但未先过滤已删除方案
3. 整体选项编号从 1 固定占用 fast/balanced/quality 三个名额，自定义方案从 4 开始，导致编号与实际可用列表不对应

### 修复方案
重写方案枚举逻辑，改为完全动态生成：
1. 从 `load_config()` 读取 `deleted_profiles` 集合
2. 遍历内置名列表 `["fast","balanced","quality"]`，跳过在 `deleted_profiles` 中的条目
3. 遍历 `config.json` 的 `profiles` 字段，将不在内置名列表中的自定义方案追加
4. 最终 `_available_profiles` 列表即为实际可选列表，从 1 开始连续编号展示
5. 增加 `config.json` 不可读时的兜底逻辑（退回显示全部三个内置方案）

### 变更文件
- `main.py`：替换 `_interactive_input()` 内第 403-436 行的方案选择代码段

### 验证方法
运行 `python main.py`，确认方案菜单仅显示 config.json 中实际可用的方案（`r18` 和 `general`），不再出现已被删除的 fast / balanced / quality；选择编号后 `--profile` 参数与所选方案名一致。

---

## [2026-06-05 16:12] 新增：启动时检测可用模型方案完整性

### 问题描述
- 现象：若用户未配置 API Key 或 config.json 缺少提供商信息，程序会在翻译步骤才报错（EnvironmentError），此前的术语提取、HTML 解析等步骤均已完成，浪费用户时间。
- 影响范围：所有用户，尤其是初次配置时未正确设置 API Key 的情况。

### 根本原因
启动流程缺少前置配置完整性校验，所有校验均推迟到实际调用 LLM API 时才触发。

### 修复方案
在 `main()` 入口处（交互式/CLI 分支之前）新增 `_check_profile_ready()` 调用：
- 先调用 `_llm_load_env()` 加载 .env 文件
- 遍历所有可用方案（过滤 `deleted_profiles`，含未删除内置方案 + 自定义方案）
- 对每个方案验证 `term_extractor` / `translator` / `polisher` 三个 agent 均能解析出 `base_url` / `model` / `api_key_env`，且 `api_key_env` 对应环境变量已设置且非空
- 至少一个方案通过则静默继续；全部失败则打印友好配置提示并 `sys.exit(1)`
- `config.json` 不存在或解析失败视为无可用方案，同样触发提示并退出

### 变更文件
- `main.py`：
  - 导入行新增 `load_config as _llm_load_config` 和 `_load_env as _llm_load_env`
  - 新增 `_check_profile_ready()` 函数（含配置加载、方案枚举、全量验证逻辑）
  - 新增 `_validate_profile()` 辅助函数（单方案可用性验证）
  - 新增 `_print_no_profile_hint()` 辅助函数（友好错误提示）
  - `main()` 入口第一行调用 `_check_profile_ready()`

### 验证方法
临时注释 .env 中的 API Key 后运行 `python main.py test\<任意>.html`，应在解析 HTML 之前打印配置缺失提示并退出（exit code 1）；恢复 API Key 后正常运行。

---
