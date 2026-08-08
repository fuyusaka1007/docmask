# Changelog

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
