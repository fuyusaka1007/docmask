# Changelog

## v0.1.0-beta.4 (2026-08-09)

基于《代码完整审计报告-20260809.md》修复全部 20 项审计发现（1 P0 / 11 P1 / 7 P2 / 1 P3），270 个测试通过。

### 修复（P0）

- **超长文本正则静默漏脱敏（A-01）**：大于 256 KiB 的 TXT 文件截断后正则规则仅匹配前半部分，尾部敏感信息直接泄漏但任务仍显示成功。改为 fail closed：含正则规则且文本超限时抛出 `RegexBudgetExceededError`，精确规则仍对全文匹配；TXT 处理器捕获异常后标记文件失败，不生成输出
- **pip install 不安装 regex，ReDoS 保护静默降级（A-03）**：`setup.py` install_requires 缺 `regex`；`codebook.py` 导入失败时静默回退标准库 `re`（无 per-call timeout）。`setup.py` 新增 `regex>=2024.0`；无 `regex` 模块时含正则规则的密码本在 `_parse()` 阶段抛出 `CodebookError`，明确拒绝加载

### 修复（P1）

- **DOCX 残留扫描绕过正则超时保护（A-04）**：`pattern.search(text)` 无 timeout。新增 `codebook.safe_search()` 统一安全搜索 API，per-call timeout 2 秒；所有 DOCX 扫描阶段的正则搜索统一走安全路径
- **DOCX 冲突预检与实际替换采用不同文本坐标（A-05）**：`_collect_all_text()` 逐节点收集，`_mask_direct_runs()` 连续节点拼接处理，跨 Run 脱敏词漏检。预检改为复用 `_iter_direct_text_groups()` 生成连续文本组
- **DOCX 保存后残留校验"部分文本已改变"时漏报（A-06）**：仅检查文本值是否完全等于快照中的值，部分替换后跳过。改为逐节点核对：记录每个文本节点身份，保存后检查部分替换的节点是否仍包含规则原文
- **密码本存在 ERROR 时仍保存并生成版本（A-02）**：`update_rules()` 返回错误后无条件 `lib.save()`。先校验后提交：含 ERROR 时禁止保存，`codebook_library.save()` 写入前执行独立临时 Codebook 解析 + validate
- **密码本编辑器静默丢弃未填完整的规则行（A-07）**：空字段行被 `continue` 跳过，保存后永久消失。改为返回所有行，空字段行标记为 ERROR 并阻止保存
- **密码本库保存跨四文件无事务（A-08）**：依次写 current.txt → 版本 → meta.json → index.json，非原子。引入 commit marker 事务：版本快照先写入，commit marker 记录目标 meta，依次更新各文件后删除 marker；启动时检测并恢复中断的保存
- **历史记录批量写入在 Tk 主线程执行，O(n²)（A-09）**：逐条 `append()` 每条 flush+fsync+重新计数。新增 `append_many()` 批量写入（一次序列化、一次写入、一次 fsync）；`record_history()` 收集后通过后台线程执行
- **停止任务无法及时停止 DOC 转换（A-10）**：`subprocess.run(timeout=120)` 阻塞无取消轮询。改为 `subprocess.Popen` + 短周期 `communicate(timeout=0.5)` 循环，收到取消令牌后终止进程
- **大型 TXT/大量匹配高内存占用（A-11）**：一次性读取整个文件、收集所有候选后统一排序。新增文件大小预算（50 MB）和候选数量上限（200,000），超限时拒绝处理
- **任务运行期间全局状态仍可变，历史可能记录错误密码本（A-12）**：引擎取一次密码本，历史记录重新读取当前 state。引入不可变 `TaskContext`（frozen dataclass）快照，任务期间不依赖可变全局状态

### 修复（P2）

- **DOCX 恢复没有保存后残留验证（A-17）**：恢复保存后直接提交无校验。新增对称恢复校验：检查精确规则脱敏词是否仍残留
- **三/四节点拆分扫描实际失效（A-13）**：窗口 > 2 时要求拼接结果存在于 `original_texts`（只含逐节点文本），导致 3/4 节点窗口为死代码。移除该条件，直接对相邻节点窗口执行规则检测
- **文件拖放解析丢文件，拖入目录阻塞 UI（A-14）**：正则解析 DnD 数据花括号匹配时丢弃无空格路径；拖入目录同步扫描。改为优先使用 `tk.splitlist` 标准解析；拖入目录统一走 `add_folder_async()` 异步扫描
- **GUI 格式过滤器只影响目录扫描（A-15）**：`add_files()` 不检查 `format_filters`。新增统一 `_is_format_allowed()` 函数，手动选择/拖放的文件也检查格式过滤器
- **CLI 空输入返回成功码 0（A-16）**：未找到文件时返回 0。改为默认返回 2；新增 `--allow-empty` 参数显式允许空任务成功；`collect_files()` 不再丢弃访问错误
- **结果与历史对停止/冲突信息展示不完整（A-18）**：结果页未单独统计 STOPPED；历史只保存 `error_message` 不保存 `conflict_details`。结果页增加"已停止"统计卡片；历史记录 error 字段使用 `error_message or conflict_details`；历史页面停止详情正确显示
- **密码本库索引缺少结构与路径校验（A-19）**：JSON 解析失败静默返回空库；`_codebook_dir()` 直接拼接 ID；`delete()` 执行 `shutil.rmtree()`。新增 ID 正则校验（`^cb-[0-9a-f]{8}$`）、版本 ID 校验、路径 `resolve()` 越界检查；索引损坏时从子目录重建

### 修复（P3）

- **UI 回调异常隔离器本身可能再次抛异常（A-20）**：`callback.__name__` 对 partial/callable 对象可能抛 `AttributeError`。改为 `getattr(callback, "__name__", repr(callback))`

### 变更

- 版本号升级至 `0.1.0-beta.4`
- `setup.py` install_requires 新增 `regex>=2024.0`
- 测试新增 52 个回归用例（A-01~A-20 全覆盖），总计 270 个测试通过

## v0.1.0-beta.3 (2026-08-08)

密码本库管理、版本历史、历史记录页面与集成，以及白屏修复。

### 新功能

- **密码本库管理**：多密码本集中管理，支持创建、编辑、复制、重命名、删除、导入/导出。库密码本存储在用户数据目录 `codebooks/` 下，独立于文件系统密码本
- **版本快照**：每次保存密码本自动生成版本快照（最多保留 20 个），支持查看变更摘要和一键恢复到任意历史版本
- **历史记录页面**：自动记录每次脱敏/恢复任务（最多 1000 条），支持按日期、模式、文件名筛选和查看详情。可在设置中开启/关闭历史记录
- **密码本编辑器增强**：支持批量粘贴规则、规则增删改实时同步、正则规则自动补全前缀
- **工作台联动**：从库加载密码本后自动跳转工作台，PathPicker 显示库密码本名称

### 修复

- **页面切换白屏（P1）**：`_show_page` 在 `pack_forget` 旧页面前未构建新页面，导致短暂白屏。改为先构建+`on_show`，再切换可见性
- **Tab 切换白屏**：`_show_tab` 同样存在先隐藏后渲染的问题，采用相同修复策略
- **`update_idletasks()` 强制重绘**：Tk 仅将重绘事件加入队列，`pack()` 后需调用 `update_idletasks()` 强制立即处理几何计算和画布重绘
- **历史记录阻塞 UI 重绘**：`record_history` 的 `fsync` 磁盘 I/O 与页面切换在同一事件批次执行，导致白屏。改用 `tk_root.after(50)` 延迟到独立事件
- **保存后规则消失**：`_on_save` 重新加载密码本后未同步 `_edit_rules`，导致编辑器空白。新增 `_sync_edit_rules()` 方法在增删改前同步 UI 输入
- **加载密码本跳转工作台**：`_on_edit`/`_on_create` 调用 `_on_load` 会意外跳转工作台。新增 `navigate` 参数控制是否跳转
- **批量粘贴静默丢弃无效行**：添加 `skipped` 计数，丢弃行数 > 0 时弹出警告
- **测试数据污染历史记录**：`conftest.py` autouse fixture 隔离 `user_data_dir`，`test_ui_controller.py` 设置 `history_enabled = False`

### 变更

- 新增 `docmask/services/codebook_library.py`（CodebookLibrary 多密码本管理）
- 新增 `docmask/services/history_store.py`（HistoryStore JSONL 存储）
- 新增 `docmask/ui/pages/history_page.py`（历史记录页面）
- 新增 `tests/conftest.py`（测试数据隔离）
- 新增 `tests/test_codebook_library.py`、`tests/test_codebook_edit.py`、`tests/test_history_store.py`
- 新增 SVG 图标：`check.svg`、`copy.svg`、`download.svg`、`history.svg`
- `docmask/ui/app.py`：`_show_page` 重排执行顺序 + `update_idletasks()`
- `docmask/ui/controller.py`：新增 `_schedule_record_history`、`save_codebook_to_library`、`load_library_codebook`、`rename_codebook` 等方法
- `docmask/ui/pages/codebook_page.py`：重构为库管理 + 编辑器 + 版本三 Tab 布局
- `docmask/ui/pages/workbench_page.py`：库密码本名称联动 PathPicker
- `docmask/ui/state.py`：新增 `history_enabled`、`edit_rules`、`library_id`、`library_name` 等字段
- 版本号升级至 `0.1.0-beta.3`

## v0.1.0-beta.2 (2026-08-08)

### 修复

- **macOS 触控板滚动弹跳修复**：到达滚动边界后，触摸板动量噪声产生的反向小 delta（-1/-2）会导致视图反复弹跳。新增边界锁机制：到达边界后 200ms 内抑制反方向小 delta（< 3 units），每次正 delta 被边界拦截时刷新锁计时器。大幅主动滚动（>= 3 units）不受锁限制
- **滚动诊断增强**：`_on_content_configure` / `_on_canvas_configure` 新增诊断记录，捕获 Configure 事件的 yview 变化，用于排查反馈环

### 变更

- `scroll_frame.py` 新增 `_BOUNDARY_LOCK_MS` / `_BOUNDARY_LOCK_THRESHOLD` 常量和 `_boundary_lock_dir` / `_boundary_lock_until` 状态
- `scroll_frame.py` 新增 `boundary_lock_suppressed` 诊断事件类型
- Windows 打包脚本 `build_windows.ps1` 修复了 `--add-data` 相对路径问题（来自 ad59a73）

## v0.1.0-beta.1 (2026-08-04)

第一个测试版本，供小范围用户试用。

### 核心功能

- **脱敏引擎**: 精确匹配 + 正则规则，一次遍历最长匹配优先，防反向引用注入
- **恢复引擎**: 精确规则可逆恢复，正则规则不可逆（设计限制）
- **密码本校验**: 多层校验（重复定义、脱敏词冲突、交叉冲突、空匹配正则等）
- **冲突预检**: 脱敏前扫描全文，检测脱敏词是否已存在于原文中
- **残留校验**: 保存后重新读取，确保支持范围内无遗漏
- **自污染防护**: 快照机制区分原文与脱敏后文本，避免脱敏词自身字符导致误报

### 支持格式

| 格式 | 处理方式 | 覆盖范围 |
|------|---------|---------|
| TXT | 直接读写 | 编码自动检测（UTF-8/GBK），输出统一 UTF-8 + LF |
| DOCX | XML 级别操作 | 正文、表格、页眉页脚、文本框、脚注尾注、超链接、批注、元数据、SDT 内容控件 |
| DOC | 转换后委托 | LibreOffice / Microsoft Word 转为 DOCX 后处理 |

### CLI 命令

- `docmask mask` — 文档脱敏
- `docmask restore` — 文档恢复
- `docmask check` — 密码本校验
- 支持单文件/目录批处理、格式过滤、覆盖率报告

### GUI 界面

- 工作台：脱敏/恢复模式切换，文件队列，进度展示
- 密码本管理：校验详情，规则统计，风险检查
- 任务结果：状态筛选，覆盖率报告（匿名化）
- 设置：主题/缩放/默认格式/日志管理
- 拖放添加文件（依赖 tkinterdnd2，未安装时自动降级）
- 设置持久化（主题、缩放等保存到 settings.json）

### 安全保障

- 完全离线运行，不调用在线 API
- 原子写入（基于硬链接，不会产生半成品文件）
- 线程安全的任务取消机制
- 日志不记录具体替换内容

### Windows 版本

- 已提供 Windows 预编译可执行文件：
  - `docmask-cli.exe` — 命令行可执行文件（约 16 MB）
  - `docmask-ui.exe` — GUI 可执行文件（约 27 MB）
- Windows 版本由 `build_windows.ps1` 在 Windows 10/11 上构建
- 修复了 `build_windows.ps1` 中 `--add-data` 相对路径在 PyInstaller workpath 下解析失败的问题

### 已知问题

- macOS 触控板滚动边界弹跳已在 beta.2 修复（边界锁机制）

### 技术变更摘要

- 删除了 Aho-Corasick 自动机（pyahocorasick 依赖），统一使用组合正则
- 统一 TXT 输出编码为 UTF-8（无 BOM）+ LF 换行
- python-docx 最低版本升级到 1.0
- Python 最低版本要求 3.10
- DOCX SDT 内容控件盲区已修复
- 文件路径去重使用 os.path.realpath() 规范化
- --verify 参数已隐藏（仍可用）
