# DocMask 项目交接文档

> 最后更新：2026-08-04
> 当前项目路径：`C:\Users\Administrator\Desktop\docmask`（Windows）
> 适用读者：完全没有上下文的新会话

---

## 1. 项目是什么

DocMask 是一款纯本地运行的文档脱敏工具（Python）。精确规则支持 mask→restore；正则规则不保存原始匹配值，因此明确视为不可逆。支持 TXT / DOCX / DOC 三种格式，完全离线，不调用在线 API。

完整设计参见 `开发文档.md`，快速上手参见 `README.md`。

---

## 2. 我们在做什么任务

### 本轮会话（2026-08-04，Windows 环境）

用户使用 UI 程序测试脱敏，遇到两轮 RuntimeError：`保存后残留校验失败，支持部件仍存在待脱敏内容：word/document.xml`。

**第一轮：DOCX SDT 内容控件盲区修复** — `doc.paragraphs` 和 `doc.tables` 只返回 body 的直接子段落/表格，不包含 `w:sdt`/`w:sdtContent` 包裹的内容。新增 6 个方法（`_mask_sdt_blocks` / `_mask_sdt_content` / `_mask_table_xml` 及对应的 restore 版本），递归处理 sdt 内的段落、表格和嵌套 sdt，补齐 body 和表格 cell 两处 sdt 盲区。

**第二轮：脱敏词自污染导致残留校验误报** — 诊断发现文档结构极简（仅 10 个普通段落），30 个"残留"都在 `body/p/r` 路径中。根因是用户密码本的单字符规则 `0-9` 的脱敏词（`{数字占位符0}`～`{数字占位符9}`）自身包含数字，校验函数 `_contains_rule_source` 用 `key in text` 检查脱敏后文本时，脱敏词中的数字被误判为"残留"。采用方案 B 修复：脱敏前用 `_snapshot_all_texts()` 收集所有 XML 部件原始文本快照，校验时只对"值在快照中存在"的文本（即未被替换的原文）检查规则残留，脱敏后的新文本直接跳过。

### 前序会话（已完成）

| 会话 | 内容 |
|------|------|
| 审计修复 P0-10～P1-6 | DOCX OPC 能力矩阵 / CLI 原子提交 / 密码本全局唯一 / UI 线程安全 / 报告匿名化 / 文件夹后台扫描 |
| UI 原型设计 | 产出 `layout.md`（16 章设计文档）和 `docmask-ui.design/`（4 页 HTML 原型 + 视觉 tokens） |
| UI 实现 | 实现 `docmask/ui/` 下全部模块（4 页面 + 6 控件），修复白屏、嵌套滚动、底栏滚轮等问题 |
| UI 缺陷修复 | 修复 4 项缺陷，剩余 1 项（macOS 底部滚动卡顿）未解决 |
| Bug 修复 | 跨 Run 写回文字丢失、脱敏词冲突预检机制 |
| 进度回调接口 | `CancelToken`、`TaskCancelledError`、`ProgressCallback`，所有 Handler 已集成 |
| 环境迁移与打包（Windows） | 更新 requirements.txt、PyInstaller 打包 CLI/UI 双 exe、AI 辅助脱敏方案设计（`AI辅助脱敏方案.md`） |

---

## 3. 已完成了什么

### 3.1 核心引擎（已完成，稳定）

| 模块 | 文件 | 功能 |
|------|------|------|
| 密码本解析 | `docmask/core/codebook.py` | 加载、解析、校验密码本，精确规则 + 正则规则 |
| 脱敏引擎 | `docmask/core/masker.py` | 一次遍历替换 + 最长匹配优先 + 冲突预检 + 覆盖率报告 |
| 恢复引擎 | `docmask/core/restorer.py` | 逆向映射还原 |
| CLI 入口 | `docmask/cli.py` | `mask` / `restore` / `check` 子命令 |

### 3.2 文档处理器（已完成，稳定）

| 格式 | 文件 | 覆盖元素 |
|------|------|---------|
| TXT | `handlers/txt_handler.py` | 纯文本，自动编码检测 |
| DOCX | `handlers/docx_handler.py` | 正文、表格、页眉页脚、文本框、脚注尾注、超链接、元数据 |
| DOC | `handlers/doc_handler.py` | 转 .docx 后委托 DocxHandler（pywin32 / LibreOffice） |

### 3.3 进度回调与取消机制（已完成）

`docmask/handlers/base.py` 中实现：

- `CancelToken`：线程安全的取消标记（`Event` 实现）
- `TaskCancelledError`：取消时抛出的异常
- `ProgressCallback`：进度回调签名 `(current, total, message) -> None`
- `check_cancel()` / `report_progress()`：Helper 函数

所有三个 Handler 均已集成，共 14 个测试覆盖。

### 3.4 UI 实现（已完成）

`docmask/ui/` 下完整实现 4 个页面 + 6 个控件：

| 页面 | 核心功能 |
|------|---------|
| 工作台 | 模式切换（脱敏/恢复）、密码本选择与校验、文件队列、输出设置、预检并执行、进度展示 |
| 密码本 | 校验详情、精确/正则规则统计、风险检查、编写指南 |
| 任务结果 | 结果总览、按状态筛选、文件详情、覆盖率报告 |
| 设置与帮助 | 外观主题、界面缩放、默认格式与输出位置、日志管理、帮助入口 |

UI 缺陷修复：首页白屏、嵌套滚动冲突、底栏滚轮不响应、视觉对齐 — 均已修复。

### 3.5 图标系统（2026-08-03 重写完成）

**旧实现的问题**：4x 超采样画布 96x96，但 26 个手绘函数用 24x24 坐标绘制 → 图标只占左上角 1/4 → 缩小到目标尺寸后只剩 3-5px，严重过小。

**新实现**（`docmask/ui/widgets/icon.py`）：

- 解析 Lucide SVG 路径（`xml.etree.ElementTree`），提取 `path`、`rect`、`circle`、`line`、`polygon` 元素
- 实现 SVG path 命令解析（`M`/`L`/`C`/`Z`/`H`/`V`/`A`/`S`），含三次贝塞尔展平（de Casteljau）和 arc 端点参数化
- 在 4x 超采样画布上渲染，坐标按 `_SCALE` 正确缩放
- 缩放到目标尺寸后用 `CTkImage` 提供 light/dark 双模式
- **零额外依赖**：只依赖标准库 `xml.etree`、`re`、`math` + Pillow
- 26 个 Lucide SVG 图标位于 `docmask/ui/assets/icons/`
- 公共 API 保持不变：`get_ctk_image(name, size, color)`

### 3.6 文字对齐修复（2026-08-03 完成）

| 问题 | 根因 | 修复位置 |
|------|------|---------|
| 侧栏 inactive 按钮文字偏移约 1px | active=border_width=1，inactive=border_width=0，边框变化导致内容位移 | `sidebar.py`：inactive 也设 `border_width=1` + `border_color=BG_SIDEBAR`（隐藏边框） |
| 设置页 label 与控件基线不齐 | `_row_label` 无固定高度，而右侧控件高 `BTN_HEIGHT_SM` | `settings_page.py`：`_row_label` 增加 `height=BTN_HEIGHT_SM` + `anchor="w"` |
| 设置页 info 提示行图标与文字不齐 | 图标 label `anchor="n"`，文字 label 默认居中 | `settings_page.py`：图标改为 `anchor="center"` |
| 左下角 shield 图标与"纯本地运行"文字重叠 | `CTkLabel` 默认 `compound="center"`，同时设 image+text 时文字覆盖图标 | `sidebar.py`：拆为独立的图标 label + 文字 label |

### 3.7 测试套件（已完成）

107 个测试全部通过（当前以 `pytest` 实际收集结果为准），覆盖：

| 测试文件 | 测试数 | 覆盖内容 |
|---------|--------|---------|
| `test_codebook.py` | 12 | 解析、校验、冲突检测、正则校验 |
| `test_masker.py` | 11 | 精确匹配、最长匹配、正则、覆盖率报告 |
| `test_restorer.py` | 5 | 恢复、往返测试、正则不可逆 |
| `test_txt_handler.py` | 4 | TXT 读写、脱敏/恢复、序号自增 |
| `test_docx_handler.py` | 6 | DOCX 脱敏、格式保留、表格/页眉/元数据 |
| `test_conflict_precheck.py` | 11 | 冲突预检：精确/正则/多词/集成 |
| `test_file_service.py` | 15 | 文件收集、格式筛选、排序 |
| `test_integration.py` | 4 | 完整脱敏→恢复往返 |
| `test_progress_cancel.py` | 14 | 取消标记、进度回调 |
| `test_ui_controller.py` | 3 | UI 控制器执行链路 |
| `test_doc_handler.py` | 4 | DOC 转换路径、Word COM 资源释放、LibreOffice profile 清理 |
| `test_docx_complex_integration.py` | 1 | 超链接、脚注尾注、绘图与非文本节点往返 |
| **当前实际收集总数** | **107** | 含 `test_audit_p0_p1_regressions.py` 与新增 UI 回归 |

#### 3.7.1 真实旧版 DOC 集成（2026-08-04）

使用真实 OLE `.doc` 文稿在 Windows 完成两条独立链路：

| 链路 | mask / restore | 文本往返 | 进程/临时目录 | 视觉结论 |
|---|---:|---|---|---|
| Microsoft Word COM | 51 / 51 | 完全一致 | 无新增残留 | 2 页布局和“AI 生成”水印均保留 |
| LibreOffice 26.2.5.2 | 38 / 38 | 完全一致 | 无新增残留 | 正文和分页正常，但旧 DOC 转 DOCX 时水印丢失 |

原 `.doc` 的 SHA-256、大小和修改时间在测试前后完全相同。6 份 converted/masked/restored DOCX 共渲染 12 页 PNG 并逐页检查；两条链路各自的 converted 与 restored PNG 哈希逐页相同。

完整结果见 `P0-3至P0-9修复测试报告.md` 和 `test-artifacts/real_doc_20260804_v3/real-doc-integration-result.json`。

已知限制与建议：

- Windows 高保真旧 DOC 转换优先使用 Microsoft Word；LibreOffice 链路作为跨平台回退。
- LibreOffice 必须使用独立临时 `UserInstallation` profile，避免复用用户现有实例；当前实现已完成并有单元测试固定。
- 如果水印属于必须保留的业务内容，不应把 LibreOffice 旧 DOC 转换结果判定为完全保真。
- macOS + LibreOffice 尚未实机复验。

### 3.8 打包分发（已完成）

PyInstaller 打包为两个独立 exe（Windows 环境产出）：

| 文件 | 体积 | 说明 |
|------|------|------|
| `dist/docmask-cli.exe` | 15.9 MB | 命令行版，支持 `mask`/`restore`/`check` 子命令 |
| `dist/docmask-ui.exe` | 19.4 MB | 图形界面版，双击启动 |

打包入口文件：`docmask_cli.py`（CLI）、`docmask_ui.py`（UI）。

### 3.9 依赖管理（已完成）

`requirements.txt` 包含跨平台核心依赖，并在 Windows 条件安装 Word COM 所需的 `pywin32`：

```
# 核心依赖
python-docx>=1.0
chardet>=5.0
lxml>=4.9

# Windows Microsoft Word .doc 转换（非 Windows 平台自动跳过）
pywin32>=306; sys_platform == "win32"

# UI 依赖
customtkinter>=6.0.0
darkdetect>=0.8.0

# 打包分发（可选）
pyinstaller>=6.0
```

### 3.10 AI 辅助脱敏方案设计（已完成，未实现）

`AI辅助脱敏方案.md` 中详细设计了两个新功能：

**功能一：智能预读** — 使用 spaCy 中文 NER 模型自动识别文档中的敏感信息（人名、地名、组织名、身份证、手机号等），生成 codebook 供用户确认。

**功能二：泄密风险检测** — 脱敏后对文档执行安全审计，分两层：第一层规则扫描（NER 残留检测 + 正则扫描 + 覆盖率分析），第二层可选 LLM 语义审查。

### 3.11 Bug 修复（更早会话，已完成）

**修复 1：跨 Run 写回导致大段文字丢失**

`docx_handler.py` 的 `_write_back_to_runs` 和 `_write_back_to_xml_runs`，当脱敏替换导致文本长度变化时，用原文位置切片替换后文本，导致只写入片段、后续 Run 全部丢失。修复为：完整替换文本写入第一个有内容的 Run，其余清空。

**修复 2：文档级脱敏词冲突预检**

新增 `MaskConflictError` + `Masker.precheck_conflict()`，脱敏前扫描文档全文，检查脱敏词是否已自然存在于原文档中。若冲突则报错终止。

### 3.12 DOCX SDT 内容控件盲区修复（2026-08-04 完成）

`doc.paragraphs` 和 `doc.tables` 只返回 body 的直接子段落/表格，不返回被 `w:sdt`/`w:sdtContent` 包裹的内容，导致 sdt 内的段落和表格成为脱敏盲区。新增 6 个方法：

| 方法 | 作用 |
|------|------|
| `_mask_sdt_blocks` / `_restore_sdt_blocks` | 入口：遍历 body 直接子 `w:sdt` |
| `_mask_sdt_content` / `_restore_sdt_content` | 递归处理 `w:sdtContent` 内的 `w:p`、`w:tbl`、嵌套 `w:sdt` |
| `_mask_table_xml` / `_restore_table_xml` | XML 表格遍历：`w:tr`→`w:tc`→`w:p`，递归嵌套表格和 sdt |

同时在 `_mask_tables` / `_restore_tables` 的 walk 函数中补齐 cell 内 `w:sdt` 盲区（`cell._tc.findall(qn("w:sdt"))`）。

**设计要点**：`_mask_direct_runs` 只处理段落直接 Run，不递归进 txbxContent/hyperlink，因此不会与已有的 `_mask_textboxes`、`_mask_hyperlinks` 步骤重叠。

### 3.13 残留校验快照机制（2026-08-04 完成）

**问题**：用户密码本的单字符规则 `0-9` 的脱敏词（`{数字占位符0}`～`{数字占位符9}`）自身包含数字。校验函数 `_contains_rule_source` 用 `key in text` 检查脱敏后文本时，脱敏词中的数字字符被误判为"规则原文残留"，导致 fail-closed 误报。

**修复**（方案 B——快照比较）：

1. 新增 [`_snapshot_all_texts`](file:///c:/Users/Administrator/Desktop/docmask/docmask/handlers/docx_handler.py#L760)：脱敏前收集所有 XML 部件的文本节点原始文本到 `set[str]`
2. `_assert_no_supported_residuals` 改为逐个检查文本值：只有 `value in original_texts`（说明是未被替换的原文）且 `_contains_rule_source(value)` 才报残留；脱敏后的新文本直接跳过
3. `_scan_unsupported_parts` 同步修改用快照过滤告警

**效果**：即使脱敏词包含规则原文字符，也不会被误判为残留。但真正的盲区（如某段原文完全未被脱敏处理）仍会被正确检出。

---

## 4. 当前卡在哪

### 4.1 macOS 触摸板滚动问题（未解决，macOS 专属）

这是两个相关但可能处于不同页面的问题：

**问题 A：底部滚动卡顿** — 工作台内容区下滑到底部后，持续上滑时页面跳动/卡顿（`bottom=1.0` 与约 `0.987` 之间反复变化）。此问题在更早会话中出现，当时为 Windows 环境无法复现。

**问题 B：完全无法下滑** — 本次会话中，macOS 触摸板在某些页面上完全无法滚动。

**根因分析（本次确认）**：

CustomTkinter 的 `CTkScrollableFrame` 每个实例都在构造时执行：
```python
self.bind_all("<MouseWheel>", self._mouse_wheel_all, add=True)
```
App 中有多个 page 级滚动容器（工作台、密码本、设置、结果页），每个都注册了全局事件处理。多个 handler 看到同一个滚轮事件时会产生冲突。

`_check_if_valid_scroll` 仅按 widget 树层级过滤，无法区分"一个鼠标位置同时属于多个滚动容器"的场景。macOS 触控板产生高频、小 delta 事件，冲突下极易表现为无响应或跳动。

**已排除的原因**：文件队列嵌套滚动（已移除）、页面内容高度变化、自定义处理器未绑定成功。

**已尝试但失败的 5 种方案**（均已回退，不要重复尝试）：

1. 方向切换去抖
2. 底部方向锁定
3. 120ms / 250ms 惯性过滤窗口
4. 同一 Tk 空闲周期合并滚轮增量
5. 工作台专属 bindtag

**建议的彻底解决方案**：

- 用 tkinter 原生 `tkinter.Canvas` + `tkinter.Frame` 自实现滚动容器，替代 `CTkScrollableFrame`
- 或只让当前可见 page 的滚动容器绑定全局事件（`unbind_all` 不可行，会清掉所有实例的绑定，需改用 `bind` 到具体 Canvas）

### 4.2 调试插桩待清理

`app.py`、`codebook_page.py`、`workbench_page.py` 中遗留了上一阶段白屏调试的 `_debug_event()` 调用（NDJSON 日志上报到 `http://127.0.0.1:7777`）。这些不会影响正常功能（try/except 包围），但应在 UI 稳定后清理。

### 4.3 统计卡片竖条问题（已知但未修复）

`codebook_page.py` 用 `place()` + 3px 宽 `CTkFrame` 模拟统计卡片的左边框颜色条，与圆角卡片视觉冲突。需评估是否值得改为自定义绘制或接受视觉效果。

### 4.4 密码本占位符问题（3.13 快照机制已绕过，但未根除）

用户密码本中数字规则使用 `{数字占位符0}`～`{数字占位符9}` 作为脱敏词，自身包含数字 `0-9`。3.13 的快照机制已通过区分"原文"和"脱敏后文本"绕过了 `_contains_rule_source` 的误报，**脱敏功能已能正常完成**。但长期来看：
- 脱敏词含规则原文字符仍是坏味道，如果未来有人修改校验逻辑、或用其他工具分析脱敏后的 docx，仍可能混乱
- 建议改为 `⟦DM-D0⟧` 等不含任何规则原文的专用占位符
- 用户暂不处理

---

## 5. 下一步计划

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | macOS 滚动问题彻底解决 | 用原生 Canvas+Frame 替换 CTkScrollableFrame 或改为页面级滚动绑定。详见第 4.1 节。 |
| P0 | 调试插桩清理 | 待 UI 稳定后移除所有 `_debug_event` 调用和 `.dbg/` 目录。 |
| P1 | 统计卡片竖条修复 | `codebook_page.py` 的 `place()` 矩形色条与圆角卡片冲突。 |
| **待用户决定** | 功能三：UI 图形化编辑 codebook | 在 UI 中直接增删改 codebook 规则，无外部依赖。 |
| **待用户决定** | 功能一：智能预读（NER 自动标记） | spaCy 中文 NER 识别敏感信息 → 自动生成 codebook，需与功能三联动。 |
| **待用户决定** | 功能二：泄密风险检测 | 脱敏后安全审计。 |
| 待用户决定 | 密码本占位符改造 | 将 `{数字占位符0}` 等改为不含规则原文的专用占位符（如 `⟦DM-D0⟧`）。当前被 3.13 快照机制绕过，脱敏已可用。 |

---

## 6. 踩过的坑绝对不要再踩

### 坑 1：跨 Run 写回绝不能用原文位置切片替换后文本

**错误做法**：用原文中各 Run 的起始位置（`pos_before`）去切片**替换后的文本**。当替换导致长度变化时，`pos_before` 指向的位置在替换后文本中已经错位，导致只写入了片段，后续 Run 被清空。

**正确做法**：长度不变时按原 Run 长度切分写回；长度变化时完整替换文本写入第一个有内容的 Run，其余清空。

**涉及方法**：`_write_back_to_runs()` 和 `_write_back_to_xml_runs()`（两个方法有相同的 bug，必须同步修复）。

### 坑 2：脱敏词不能是文档中可能自然出现的字符

脱敏词必须满足三个条件才能保证可逆：
1. 每个脱敏词唯一
2. 脱敏词不属于任何原文规则
3. **脱敏词不存在于待处理文档中**（文档级预检）

用户当前密码本的数字规则（`0==>!` 到 `9==>@`）全部使用常见符号作为脱敏词，几乎必然与文档内容冲突。必须改为专用占位符（如 `⟦DM-D0⟧`）。

### 坑 3：macOS / zsh 下不要用 `&&` 连接 Windows 命令

在 macOS 上操作时不影响，但如果用 `&&` 连接命令后复制到 Windows PowerShell 执行会报 ParserError。在 Windows 上使用 `;` 分隔命令。另外 TRAE IDE 内置 Python 3.10 缺少 tkinter，UI 必须用系统安装的 Python。

### 坑 4：正则规则不可逆

正则规则匹配的内容在恢复时无法还原，因为正则匹配的是模式而非精确字符串。需要完整还原的场景应避免使用正则规则。

### 坑 5：`_current_page` 不能初始化为目标页面名

`_show_page()` 通过 `if page_id == self._current_page: return` 做去重。如果 `_current_page` 初始值设为目标页面名（如 `"workbench"`），首次调用会提前返回，不执行 `pack`，导致白屏。

**正确做法**：初始化为 `None`。

### 坑 6：CustomTkinter `CTkScrollableFrame` 不能嵌套

`CTkScrollableFrame` 通过 `bind_all("<MouseWheel>")` 注册全局滚轮处理器。两个嵌套的 `CTkScrollableFrame` 会导致滚轮事件被两个实例同时处理，产生不可预期的滚动行为。

**正确做法**：外层用 `CTkScrollableFrame`，内层用普通 `CTkFrame`；或将滚动统一交给最外层容器。

### 坑 7：macOS 触控板 + 多个 CTkScrollableFrame → 滚轮不可靠

App 中多个页面各自有 `CTkScrollableFrame` 实例，每个都注册全局 `bind_all("<MouseWheel>")`。即使切换页面 pack_forget 了旧页面，bind_all 不会自动清理。这是 macOS 滚动问题的根因。解决方案见第 4.1 节。

### 坑 8：超采样渲染时坐标必须按 `_SCALE` 同步缩放

**错误做法**：4x 超采样画布 96x96，但绘制函数仍用 24x24 坐标 → 图标只占左上角 1/4，缩小后只剩 3-5px。

**正确做法**：所有坐标在渲染前乘以缩放因子。参见 `icon.py` 的 `_draw_subpath()`：`scaled = [(p[0] * s, p[1] * s) for p in points]`。

### 坑 9：svglib + reportlab 在 Python 3.13 上不可用

reportlab 5.x 依赖 rlPyCairo（需 pycairo + 系统 cairo），4.x 纯 Python wheel 不含 `_rl_renderPM` C 扩展，Python 3.13 没有对应的预编译 wheel。

**不要重复尝试这个方案**。如果需要 SVG→PIL 转换，用 `xml.etree.ElementTree` 直接解析 SVG + PIL `ImageDraw` 渲染（即当前方案），这是零额外依赖的正确路径。

### 坑 10：CTkLabel 同时设 image+text 时默认 compound="center"

`CTkLabel` 同时设置 `image` 和 `text` 时，默认 `compound="center"`（文字叠加在图标上）。如果意图是图标在文字左侧，必须显式设置 `compound="left"`。对于只有 icon 没有 text 的 label，不要设置 text（设为 `""` 即可）。切勿给纯图标 label 设置非空 text 字符串。

### 坑 11：CTkButton active/inactive 切换 border_width 会导致文字位移

当 active 状态 `border_width=1` 而 inactive 状态 `border_width=0` 时，边框从无到有会让按钮内部文字产生 1px 偏移。修复方式：inactive 也保持 `border_width=1`，但将 `border_color` 设为与背景同色（视觉上隐藏边框，但空间不变）。

### 坑 12：设置页行内 label 需要固定高度以对齐同行控件

`CTkOptionMenu` / `CTkCheckBox` / `CTkRadioButton` 有固定高度，但普通 `CTkLabel` 默认为内容自适应。同一行内 label 和控件用 `pack(side="left")` 混合布局时，label 需要明确设置 `height` 和 `anchor="w"` 才能使文字基线对齐。

### 坑 13：`polygon` 元素需要单独处理

Lucide 的 `play.svg` 使用 `<polygon points="..."/>` 而非 `<path d="..."/>`。SVG 解析器必须同时支持 `path`、`rect`、`circle`、`line`、`polygon` 五种元素。

### 坑 14：脱敏词含规则原文字符 + `key in text` 校验 = 必然误报

**场景**：密码本有规则 `1==>{数字占位符1}`，脱敏词 `{数字占位符1}` 自身包含数字 `1`，而 `1` 又是另一条规则的原文。校验函数用 `key in text` 检查脱敏后文本时，脱敏词中的 `1` 被命中，误报为"残留"。

**根因**：`_contains_rule_source` / `_assert_no_supported_residuals` 不区分"脱敏的词"和"没脱敏的词"，对所有文本无差别做 `key in text` 检查。

**当前方案**：脱敏前用 `_snapshot_all_texts()` 保存原始文本快照，校验时只对"值在快照中存在"的文本（未被替换的原文）做检查。长期应让用户改用不含规则原文的脱敏词（如 `⟦DM-D1⟧`）。

### 坑 15：`doc.paragraphs` / `doc.tables` 不返回 sdt 内的内容

python-docx 的 `Document.paragraphs` 只返回 `<w:body>` 的直接子 `<w:p>`，`Document.tables` 只返回直接子 `<w:tbl>`；被 `<w:sdt>`/`<w:sdtContent>` 包裹的段落和表格不在其中。

**盲区**：body 直接子 sdt、表格 cell 内 sdt、sdt 内表格内 sdt——三层都要覆盖，且要递归处理。

**正确做法**：对 body 直接子 sdt 调用 `_mask_sdt_blocks`（递归 sdt 内的段落/表格/嵌套 sdt）；在 `_mask_tables` 中对每个 cell 用 `cell._tc.findall(qn("w:sdt"))`；在 `_mask_table_xml` 中对表格 cell 也做同样处理。详见 3.12 节。

### 坑 16：单字符精确规则的脱敏词不能包含自身或其他规则原文

如果密码本有 `0` 到 `9` 十个单字符精确规则，那么**任何脱敏词都不能包含数字 0-9**（即使是 `{数字占位符1}` 也不行），否则校验时会被 `key in text` 命中。

即使 3.13 的快照机制绕过了 `_assert_no_supported_residuals` 的检查，`_collect_all_text` 的文本拼接、`_scan_unsupported_parts` 的外部 URL 检查等路径仍可能出问题。

**正确做法**：单字符规则的脱敏词必须使用该字符集之外的符号，如 `⟦D0⟧`、`【零】` 等。或放弃单字符规则，改用更具体的多字符规则（如用正则匹配完整日期格式 `\d{4}年\d{1,2}月` 替代单独的 `0-9` 规则）。

---

## 7. 关键文件速查

### 7.1 核心代码

| 文件 | 作用 |
|------|------|
| `docmask/core/codebook.py` | 密码本解析与校验 |
| `docmask/core/masker.py` | 脱敏引擎，核心替换逻辑 + 冲突预检 |
| `docmask/core/restorer.py` | 恢复引擎 |
| `docmask/handlers/base.py` | Handler 基础接口：CancelToken、ProgressCallback |
| `docmask/handlers/txt_handler.py` | TXT 文件处理 |
| `docmask/handlers/docx_handler.py` | DOCX 文件处理（按 OPC 能力矩阵分为支持/告警范围） |
| `docmask/handlers/doc_handler.py` | DOC 文件处理（转换+委托） |
| `docmask/services/file_service.py` | 文件收集与 Handler 分发 |
| `docmask/cli.py` | 命令行入口 |
| `docmask/config.py` | 全局配置常量 |

### 7.2 UI 代码

| 文件 | 作用 |
|------|------|
| `docmask/ui/app.py` | 主窗口、侧边导航、页面切换（含调试插桩） |
| `docmask/ui/controller.py` | 任务控制器，后台线程调度 |
| `docmask/ui/state.py` | 应用状态、文件项、模式枚举 |
| `docmask/ui/theme.py` | 主题色板、字体、间距常量 |
| `docmask/ui/pages/workbench_page.py` | 工作台页面（含调试插桩） |
| `docmask/ui/pages/codebook_page.py` | 密码本页面（含调试插桩） |
| `docmask/ui/pages/results_page.py` | 任务结果页面 |
| `docmask/ui/pages/settings_page.py` | 设置页面 |
| `docmask/ui/widgets/icon.py` | **图标系统核心**：SVG 路径解析 + PIL 渲染 + CTkImage 封装 |
| `docmask/ui/widgets/sidebar.py` | 侧边导航栏 |
| `docmask/ui/widgets/path_picker.py` | 路径选择器 |
| `docmask/ui/widgets/file_queue.py` | 文件队列（表格布局） |
| `docmask/ui/widgets/status_badge.py` | 状态徽章 |
| `docmask/ui/widgets/dialogs.py` | 确认对话框、冲突详情对话框 |
| `docmask/ui/assets/icons/` | 26 个 Lucide SVG 图标文件 |

### 7.3 打包入口

| 文件 | 作用 |
|------|------|
| `docmask_cli.py` | PyInstaller CLI 打包入口 |
| `docmask_ui.py` | PyInstaller UI 打包入口 |

### 7.4 文档

| 文件 | 作用 |
|------|------|
| `开发文档.md` | 完整设计文档（功能需求、技术方案、模块设计） |
| `layout.md` | UI 原型设计完整文档（16 章） |
| `AI辅助脱敏方案.md` | AI 辅助脱敏技术方案 |
| `README.md` | 快速上手 |
| `HANDOFF.md` | 项目交接文档（本文件） |
| `requirements.txt` | 依赖列表 |

### 7.5 测试

| 文件 | 测试数 |
|------|--------|
| `tests/test_codebook.py` | 12 |
| `tests/test_masker.py` | 11 |
| `tests/test_restorer.py` | 5 |
| `tests/test_txt_handler.py` | 4 |
| `tests/test_docx_handler.py` | 6 |
| `tests/test_conflict_precheck.py` | 11 |
| `tests/test_file_service.py` | 15 |
| `tests/test_integration.py` | 4 |
| `tests/test_progress_cancel.py` | 14 |
| `tests/test_ui_controller.py` | 3 |
| **当前实际收集总数** | **107** |

---

## 8. 如何验证当前状态

### 8.1 启动 UI 应用

```bash
# macOS 环境
python -c "from docmask.ui import launch; launch()"
```

### 8.2 语法检查

```bash
# 主要 UI 文件
python -m py_compile docmask/ui/app.py \
  docmask/ui/pages/workbench_page.py \
  docmask/ui/pages/codebook_page.py \
  docmask/ui/pages/results_page.py \
  docmask/ui/pages/settings_page.py \
  docmask/ui/widgets/icon.py \
  docmask/ui/widgets/sidebar.py

# 核心模块
python -m py_compile docmask/core/codebook.py docmask/core/masker.py docmask/core/restorer.py
```

### 8.3 运行测试套件

```bash
python -m pytest tests/ -v
# 预期：107 passed
```

### 8.4 CLI 脱敏流程验证

```bash
python -m docmask check -c tests/test_data/sample_codebook.txt
python -m docmask mask -c tests/test_data/sample_codebook.txt -i tests/test_data/sample.txt
```

### 8.5 图标渲染测试

```bash
python -c "
from docmask.ui.widgets.icon import get_icon_image
for name in ['shield-check','workflow','book-open','clipboard-list','settings',
             'play','trash','plus','info','alert-triangle','check-circle','search',
             'eye','refresh','folder-open','folder-plus','folder-search','file-text',
             'chevron-down','chevron-right','help-circle','rotate-ccw','file-check',
             'square','external-link','shield']:
    img = get_icon_image(name)
    print(f'{name}: {img.size} {"OK" if img.getbbox() else \"EMPTY!\"}')
"
# 预期：26 个图标全部 OK
```

### 8.6 打包（macOS）

```bash
# CLI 版
python -m PyInstaller --onefile --name docmask-cli \
  --hidden-import lxml --hidden-import chardet \
  docmask_cli.py

# UI 版
python -m PyInstaller --onefile --windowed --name docmask-ui \
  --hidden-import customtkinter --hidden-import darkdetect \
  --hidden-import lxml --hidden-import chardet \
  docmask_ui.py
```

---

## 9. 环境信息

- **操作系统**：macOS（Apple Silicon / ARM64）
- **项目路径**：`/Users/fuyusaka/Desktop/projects/docmask`
- **Python 版本**：Python 3.13（anaconda 环境）
- **CustomTkinter 版本**：6.0.0
- **PyInstaller 版本**：6.x（已安装）
- **测试框架**：pytest，107 个测试全部通过
- **Windows 环境**：项目路径 `C:\Users\Administrator\Desktop\docmask`，Python 3.14.6，CustomTkinter 6.0.0
