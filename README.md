# DocMask - 文档脱敏工具

纯离线文档敏感信息脱敏工具，支持 TXT / DOCX / DOC 格式；精确规则可逆，正则规则不可逆。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 文档脱敏 | 精确规则可逆脱敏 + 正则规则不可逆脱敏 |
| 文档恢复 | 基于精确规则的可逆恢复 |
| 密码本库 | 多密码本集中管理，版本快照，导入/导出 |
| 历史记录 | 自动记录任务历史，支持筛选查看 |
| 格式支持 | TXT / DOCX / DOC（需 LibreOffice 或 Word） |

---

## 下载预编译版本

### Windows

从 [GitHub Releases](https://github.com/fuyusaka1007/docmask/releases) 下载 Windows 版本：

| 文件 | 说明 |
|------|------|
| `docmask-cli.exe` | 命令行可执行文件 |
| `docmask-ui.exe` | GUI 可执行文件，双击运行 |

```powershell
# CLI 示例
.\docmask-cli.exe check -c codebook.txt
.\docmask-cli.exe mask -c codebook.txt -i input.docx -o output.docx

# GUI 直接双击运行
.\docmask-ui.exe
```

### macOS

从 [GitHub Releases](https://github.com/fuyusaka1007/docmask/releases) 下载 macOS 版本：

| 文件 | 说明 |
|------|------|
| `docmask-cli` | 命令行可执行文件 |
| `docmask-ui` | GUI 可执行文件 |
| `docmask-ui-macos.app.zip` | GUI 应用包（.app） |

```bash
chmod +x docmask-cli docmask-ui
./docmask-cli mask -c codebook.txt -i input.docx -o output.docx
./docmask-ui
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备密码本

创建一个 `.txt` 文件，按以下格式编写脱敏规则：

```text
# 精确匹配规则
张三==>李四
某某科技有限公司==>甲乙科技有限公司

# 正则规则（模式匹配）
regex:\d{17}[\dXx]==>[身份证号已脱敏]
regex:1[3-9]\d{9}==>[手机号已脱敏]
```

### 3. 执行脱敏

```bash
# 校验密码本
python -m docmask check -c codebook.txt

# 脱敏单个文件
python -m docmask mask -c codebook.txt -i input.docx -o output.docx

# 脱敏整个目录
python -m docmask mask -c codebook.txt -i ./docs -f docx,txt

# 恢复脱敏文件
python -m docmask restore -c codebook.txt -i input_desensitized.docx
```

---

## 命令行参数

### 子命令

| 命令 | 说明 |
|------|------|
| `check` | 校验密码本，不执行脱敏 |
| `mask` | 执行脱敏 |
| `restore` | 恢复脱敏文档 |

### 通用参数

| 参数 | 简写 | 说明 | 默认 |
|------|------|------|------|
| `--codebook` | `-c` | 密码本文件路径 | 必填 |
| `--input` | `-i` | 输入文件或目录路径 | 必填 |
| `--output` | `-o` | 输出文件或目录路径 | 自动生成 |
| `--format` | `-f` | 限定文件格式，逗号分隔 | `docx,doc,txt` |
| `--log-level` | `-l` | 日志级别 | `INFO` |
| `--report` | `-r` | 输出脱敏覆盖率报告（仅 mask） | 关闭 |

---

## 密码本编写指南

### 格式说明

```
# 注释行
原文==>脱敏词           # 精确匹配规则
regex:正则模式==>脱敏词  # 正则规则
```

### 规则

- 分隔符是 `==>`（三个字符）
- `#` 开头的行为注释
- 空行自动跳过
- 精确规则按原文长度降序匹配（最长匹配优先）
- 精确与正则规则统一在原文坐标上匹配；替换结果不会再次参与匹配
- 同一位置优先选择最长匹配；同长度时精确规则优先，正则规则按定义顺序裁决

### 校验规则

程序会在加载密码本时自动校验，以下情况会报错：

1. **脱敏词重复**：两条不同原文映射到同一脱敏词 → 恢复时歧义
2. **交叉冲突**：某条规则的脱敏词是另一条规则的原文（如 `A==>B` + `B==>C`）
3. **正则无效**：`regex:` 后的正则表达式无法编译
4. **原文或脱敏词为空**
5. **原文重复定义**：不再采用“最后一条覆盖”，而是拒绝加载
6. **正则可匹配空字符串**：会造成不确定替换，拒绝加载
7. **全局脱敏词重复**：精确和正则规则之间也必须保持脱敏词唯一

### 内置正则示例

| 场景 | 正则规则 |
|------|---------|
| 身份证号 | `regex:\d{17}[\dXx]==>[身份证号已脱敏]` |
| 手机号 | `regex:1[3-9]\d{9}==>[手机号已脱敏]` |
| 邮箱 | `regex:[\w\.-]+@[\w\.-]+\.\w+==>[邮箱已脱敏]` |
| 银行卡号 | `regex:\d{16,19}==>[银行卡号已脱敏]` |

---

## 调试指南

### 运行测试

```bash
# 安装测试依赖
pip install pytest

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_codebook.py -v

# 运行单个测试用例
python -m pytest tests/test_masker.py::TestMasker::test_longest_match_priority -v
```

### 调试 CLI

```bash
# 开启 DEBUG 日志
python -m docmask mask -c codebook.txt -i input.txt -l DEBUG

# 查看日志文件
type docmask.log
```

### 调试 Python 代码

```bash
# 交互式调试
python -c "
from docmask.core.codebook import Codebook
from docmask.core.masker import Masker

cb = Codebook('tests/test_data/sample_codebook.txt')
cb.load()
print('Forward map:', cb.get_forward_map())
print('Sorted keys:', cb.get_sorted_keys())

masker = Masker(cb)
result, count, hits = masker.mask_text('张三和张三丰')
print('Result:', result)
print('Count:', count)
print('Hits:', hits)
"
```

### 常见问题

| 问题 | 解决方法 |
|------|---------|
| 密码本编码错误 | 用 UTF-8 保存密码本，程序会自动尝试 UTF-8/GBK |
| .doc 文件无法处理 | 安装 Microsoft Word 或 LibreOffice，或手动转为 .docx |
| 脱敏后格式丢失 | DOCX 格式保留针对正文/表格/页眉；文本框等复杂元素可能受限 |
| 恢复后与原文不一致 | 正则规则不可逆；检查密码本是否有交叉冲突 |
| 输出文件已存在 | 程序自动追加序号（如 `_desensitized_1.docx`），不会覆盖 |

### DOCX 支持边界

强保证范围包括正文、递归表格、页眉页脚、文本框、脚注尾注、批注正文与作者、
修订插入/删除文本、超链接显示文本、核心文本属性，以及有限的扩展/自定义字符串属性。
保存后会重新扫描这些部件；发现残留规则原文时拒绝提交输出。

图表、SmartArt、嵌入/OLE 对象和外部超链接目标属于告警范围，不承诺自动改写；
若其中疑似含规则原文，调用方应读取 `DocxHandler.last_warnings` 并人工复核。

### 项目结构

```
docmask/
├── core/                    # 核心引擎
│   ├── codebook.py          # 密码本解析与校验
│   ├── masker.py            # 脱敏引擎（统一原文匹配+最长匹配）
│   └── restorer.py          # 恢复引擎
├── handlers/                # 格式处理器
│   ├── txt_handler.py       # TXT
│   ├── docx_handler.py      # DOCX（段落/表格/页眉/文本框/脚注/超链接/元数据）
│   └── doc_handler.py       # DOC（pywin32/LibreOffice 转换）
├── services/               # 服务层
│   ├── codebook_library.py # 密码本库管理（多密码本、版本快照）
│   ├── history_store.py    # 历史记录存储（JSONL）
│   └── file_service.py     # 文件批量处理
├── ui/                     # GUI 界面
│   ├── app.py              # 主窗口与页面路由
│   ├── controller.py       # UI 控制器（任务调度、密码本库操作）
│   ├── state.py            # 应用状态模型
│   ├── theme.py            # 主题配置
│   ├── pages/              # 页面
│   │   ├── workbench_page.py    # 工作台
│   │   ├── codebook_page.py     # 密码本库（库/编辑器/版本三 Tab）
│   │   ├── history_page.py      # 历史记录
│   │   ├── results_page.py      # 任务结果
│   │   └── settings_page.py     # 设置
│   └── widgets/            # 可复用控件
├── utils/                   # 工具
│   ├── encoding.py          # 编码检测
│   ├── file_utils.py        # 文件路径处理
│   └── logger.py            # 日志配置
├── cli.py                   # 命令行入口
├── config.py                # 全局配置
└── __main__.py              # python -m docmask 入口
```

### 关键配置（config.py）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DESENSITIZED_SUFFIX` | `_desensitized` | 脱敏输出文件后缀 |
| `RESTORED_SUFFIX` | `_restored` | 恢复输出文件后缀 |
| `LOG_FILE` | `docmask.log` | 日志文件名 |
| `CODEBOOK_SEPARATOR` | `==>` | 密码本规则分隔符 |
| `REGEX_PREFIX` | `regex:` | 正则规则前缀 |

---

## 技术要点

- **一次遍历**：每处文本仅被替换一次，已替换部分不再参与后续匹配
- **最长匹配优先**：同一位置有多条规则可匹配时，优先匹配原文最长的规则
- **交叉冲突检测**：加载时自动检测脱敏词与原文的交叉冲突，防止恢复失败
- **隐私安全报告**：仅输出匿名规则 ID、类型和命中次数，不包含原文、替换值或正则内容
- **日志安全**：日志只记录替换次数，不记录具体替换内容，防止日志泄露
- **正则不可逆**：正则规则匹配的内容无法恢复，仅精确规则可逆
