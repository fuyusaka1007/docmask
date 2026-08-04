# DocMask AI 辅助脱敏技术方案

> 编写日期：2026-07-30
> 状态：方案设计（未实现）

---

## 目录

- [1. 总体架构](#1-总体架构)
- [2. 功能一：智能识别敏感信息，自动生成 codebook](#2-功能一智能识别敏感信息自动生成-codebook)
  - [2.1 技术选型](#21-技术选型)
  - [2.2 实体类型定义](#22-实体类型定义)
  - [2.3 模块设计](#23-模块设计)
  - [2.4 自动生成脱敏词](#24-自动生成脱敏词)
  - [2.5 与现有架构集成](#25-与现有架构集成)
  - [2.6 完整工作流](#26-完整工作流)
  - [2.7 性能估算](#27-性能估算)
- [3. 功能二：脱敏后泄密风险检测](#3-功能二脱敏后泄密风险检测)
  - [3.1 风险模型定义](#31-风险模型定义)
  - [3.2 检测层级设计](#32-检测层级设计)
  - [3.3 模块设计](#33-模块设计)
  - [3.4 与现有架构集成](#34-与现有架构集成)
  - [3.5 完整工作流](#35-完整工作流)
  - [3.6 性能估算](#36-性能估算)
- [4. 依赖与体积影响](#4-依赖与体积影响)
- [5. 打包策略](#5-打包策略)
- [6. 配置项设计](#6-配置项设计)
- [7. 里程碑与实施顺序](#7-里程碑与实施顺序)

---

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         UI 层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   工作台      │  │  密码本编辑   │  │  风险报告    │       │
│  │ +智能预读按钮 │  │ +NER结果填入  │  │  泄密指数    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
├─────────┼─────────────────┼─────────────────┼───────────────┤
│         │            Controller             │               │
│         │         (后台线程调度)             │               │
├─────────┼─────────────────┼─────────────────┼───────────────┤
│         ▼                 ▼                 ▼               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  analysis/   │  │  core/       │  │  analysis/   │       │
│  │  extractor   │  │  codebook    │  │  auditor      │      │
│  │  (功能一)    │  │  (现有)      │  │  (功能二)     │       │
│  └──────┬───────┘  └──────────────┘  └──────┬───────┘       │
│         │                                  │               │
│         ▼                                  ▼               │
│  ┌─────────────────────────────────────────────────┐       │
│  │              NER 模型（共享）                    │       │
│  │  spaCy / HanLP 中文实体识别（离线）              │       │
│  └─────────────────────────────────────────────────┘       │
├─────────────────────────────────────────────────────────────┤
│  handlers/   txt_handler / docx_handler / doc_handler      │
│  (现有，不改动)                                             │
└─────────────────────────────────────────────────────────────┘
```

**核心原则：**

- AI 能力是**可选模块**，未安装相关依赖时程序降级为纯规则模式，不影响现有功能
- NER 模型在功能一和功能二之间**共享**，只加载一次
- 现有 `handlers/` 和 `core/` 代码**不改动**，AI 模块通过新增 `analysis/` 包平行接入

---

## 2. 功能一：智能识别敏感信息，自动生成 codebook

### 2.1 技术选型

| 候选方案 | 模型 | 体积 | 中文 NER 准确率 | 推理速度(10页) | 离线性 |
|---------|------|------|----------------|---------------|--------|
| **spaCy** | `zh_core_web_trf` | ~450 MB | 高(85%+) | 2-5 秒 | 完全离线 |
| **spaCy 轻量** | `zh_core_web_sm` | ~30 MB | 中(70%) | <1 秒 | 完全离线 |
| HanLP | `hanlp` + 预训练模型 | ~200 MB | 高(83%) | 1-3 秒 | 完全离线 |
| 本地 LLM | Ollama + Qwen2.5-7B | ~5 GB | 极高(90%+) | 30-120 秒 | 完全离线 |

**推荐：spaCy `zh_core_web_trf`（主）+ `zh_core_web_sm`（轻量回退）**

理由：

1. spaCy 是 Python 生态最成熟的 NLP 库，API 稳定，社区活跃
2. `zh_core_web_trf` 基于 Transformer 架构，中文 NER 准确率达 85%+，可覆盖人名、地名、组织名、日期、金额、地址等常见类型
3. 支持自定义实体类型扩展（通过 EntityRuler 叠加规则），可以识别"项目代号""内部系统名"等业务特定实体
4. 体积 450 MB 对桌面应用可接受，且 PyInstaller 打包后模型可独立分发
5. 推理速度 2-5 秒/10 页，用户体验良好
6. 与 DocMask"纯本地、轻量"的定位一致

**不推荐本地 LLM 作为基座的原因：**

- 体积 5 GB+，对当前 16 MB 的应用体量增幅过大
- 推理速度慢（30-120 秒），不适合交互式预读
- 部署复杂（需 Ollama 运行时），不满足"双击即用"体验
- LLM 适合功能二的"语义审查层"作为可选增强，不适合功能一的基座

### 2.2 实体类型定义

spaCy `zh_core_web_trf` 内置实体类型：

| spaCy 标签 | 含义 | 对应 codebook 处理方式 |
|-----------|------|----------------------|
| `PERSON` | 人名 | 精确规则，脱敏词为占位符如 `⟦人名-001⟧` |
| `ORG` | 组织/公司名 | 精确规则 |
| `GPE` | 地缘政治实体（国家、城市、区县） | 精确规则 |
| `LOC` | 非GPE地理位置（河流、山脉、区域） | 精确规则 |
| `DATE` | 日期 | 精确规则（可选，用户可能不认为日期敏感） |
| `MONEY` | 货币金额 | 精确规则 |
| `QUANTITY` | 数量/度量 | 精确规则 |
| `PRODUCT` | 产品名 | 精确规则 |
| `EVENT` | 事件名 | 精确规则 |

**DocMask 扩展实体（通过 EntityRuler 叠加）：**

```python
# 在 spaCy NER 基础上叠加正则规则，识别 spaCy 默认不覆盖的类型
EXTENDED_PATTERNS = [
    # 身份证号
    {"label": "ID_CARD", "pattern": [{"TEXT": {"REGEX": r"\d{17}[\dXx]"}}]},
    # 手机号
    {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": r"1[3-9]\d{9}"}}]},
    # 邮箱
    {"label": "EMAIL", "pattern": [{"TEXT": {"REGEX": r"[\w\.-]+@[\w\.-]+\.\w+"}}]},
    # 银行卡号
    {"label": "BANK_CARD", "pattern": [{"TEXT": {"REGEX": r"\d{16,19}"}}]},
    # IP 地址
    {"label": "IP_ADDR", "pattern": [{"TEXT": {"REGEX": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"}}]},
]
```

### 2.3 模块设计

```
docmask/
├── analysis/                     # 新增包
│   ├── __init__.py
│   ├── entity.py                 # 实体类型定义、EntityRuler 扩展规则
│   ├── extractor.py              # 敏感信息提取器（核心）
│   ├── codebook_generator.py     # 从提取结果生成 codebook
│   └── model_loader.py          # NER 模型加载与缓存
├── core/
│   └── codebook.py               # 现有，不改动
├── handlers/
│   └── ...                       # 现有，不改动
```

**`model_loader.py` — 模型加载与缓存：**

```python
"""NER 模型加载器：懒加载，全局单例"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = None  # 全局单例，避免重复加载


def get_model():
    """
    懒加载 NER 模型。
    优先加载 zh_core_web_trf（高精度），
    回退到 zh_core_web_sm（轻量），
    都不可用则返回 None。
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    try:
        import spacy
        # 尝试高精度模型
        try:
            _MODEL = spacy.load("zh_core_web_trf")
            logger.info("NER 模型已加载: zh_core_web_trf")
        except OSError:
            # 回退到轻量模型
            try:
                _MODEL = spacy.load("zh_core_web_sm")
                logger.info("NER 模型已加载: zh_core_web_sm (轻量)")
            except OSError:
                logger.warning("未找到 spaCy 中文模型，请运行: "
                               "python -m spacy download zh_core_web_sm")
                return None

        # 叠加扩展实体规则
        from docmask.analysis.entity import EXTENDED_PATTERNS
        ruler = _MODEL.add_pipe("entity_ruler", before="ner")
        ruler.add_patterns(EXTENDED_PATTERNS)

    except ImportError:
        logger.warning("spaCy 未安装，智能预读功能不可用")
        return None

    return _MODEL
```

**`extractor.py` — 敏感信息提取器：**

```python
"""敏感信息提取器：从文档文本中识别实体"""
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from docmask.analysis.model_loader import get_model

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """提取到的单个实体"""
    text: str           # 实体文本（原文）
    label: str          # 实体类型标签（PERSON / ORG / GPE / ...）
    start: int          # 在文本中的起始位置
    end: int            # 结束位置
    source: str         # 来源段落/位置标记（用于 UI 定位）


@dataclass
class ExtractionResult:
    """提取结果"""
    entities: list[Entity] = field(default_factory=list)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def unique_texts(self) -> set[str]:
        """去重后的实体文本集合"""
        return {e.text for e in self.entities}

    def by_type(self) -> dict[str, list[Entity]]:
        """按类型分组"""
        groups: dict[str, list[Entity]] = {}
        for e in self.entities:
            groups.setdefault(e.label, []).append(e)
        return groups

    def by_type_with_count(self) -> dict[str, dict[str, int]]:
        """按类型分组并统计每个实体出现次数
        返回: {PERSON: {"张三": 3, "李四": 1}, ORG: {...}}
        """
        result: dict[str, dict[str, int]] = {}
        for e in self.entities:
            result.setdefault(e.label, {})
            result[e.label][e.text] = result[e.label].get(e.text, 0) + 1
        return result


class EntityExtractor:
    """敏感信息提取器"""

    def __init__(self):
        self._nlp = None

    def is_available(self) -> bool:
        """检查 NER 模型是否可用"""
        if self._nlp is None:
            self._nlp = get_model()
        return self._nlp is not None

    def extract(self, text: str, batch_size: int = 1000) -> ExtractionResult:
        """
        从文本中提取实体。

        长文本按段落分批处理，避免内存峰值。
        每批最多 batch_size 个字符。

        Args:
            text: 文档全文本
            batch_size: 每批处理的最大字符数
        Returns:
            ExtractionResult 包含所有识别到的实体
        """
        if not self.is_available():
            return ExtractionResult()

        result = ExtractionResult()
        # 按段落分割，每批处理一段
        paragraphs = text.split("\n")
        char_offset = 0

        # 使用 nlp.pipe 批量处理提升性能
        texts = []
        offsets = []
        current_batch = []
        current_length = 0

        for para in paragraphs:
            if not para.strip():
                char_offset += len(para) + 1
                continue

            if current_length + len(para) > batch_size and current_batch:
                texts.append("\n".join(current_batch))
                offsets.append(char_offset - current_length)
                current_batch = [para]
                current_length = len(para)
            else:
                current_batch.append(para)
                current_length += len(para) + 1
            char_offset += len(para) + 1

        if current_batch:
            texts.append("\n".join(current_batch))

        # 批量推理
        for text_chunk, offset in zip(texts, offsets):
            doc = self._nlp(text_chunk)
            for ent in doc.ents:
                result.entities.append(Entity(
                    text=ent.text,
                    label=ent.label_,
                    start=ent.start_char + offset,
                    end=ent.end_char + offset,
                    source=f"offset={offset}",
                ))

        return result

    def extract_from_file(self, filepath: str) -> ExtractionResult:
        """从文件提取实体（支持 txt/docx）"""
        ext = filepath.rsplit(".", 1)[-1].lower()
        if ext == "txt":
            from docmask.handlers.txt_handler import TxtHandler
            text = TxtHandler().read(filepath)
        elif ext == "docx":
            from docmask.handlers.docx_handler import DocxHandler
            # 复用现有的 _collect_all_text 收集全文
            from docx import Document
            doc = Document(filepath)
            text = DocxHandler._collect_all_text(doc)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

        return self.extract(text)
```

**`codebook_generator.py` — 从提取结果生成 codebook：**

```python
"""从 NER 提取结果生成 codebook 规则"""
import logging
from typing import Optional

from docmask.analysis.extractor import ExtractionResult
from docmask.config import CODEBOOK_SEPARATOR, REGEX_PREFIX

logger = logging.getLogger(__name__)

# 实体类型 → 中文标签 → 脱敏词前缀
TYPE_CONFIG = {
    "PERSON":    {"label": "人名",     "prefix": "⟦人名"},
    "ORG":       {"label": "组织",     "prefix": "⟦组织"},
    "GPE":       {"label": "地名",     "prefix": "⟦地名"},
    "LOC":       {"label": "位置",     "prefix": "⟦位置"},
    "DATE":      {"label": "日期",     "prefix": "⟦日期"},
    "MONEY":     {"label": "金额",     "prefix": "⟦金额"},
    "ID_CARD":   {"label": "身份证",   "prefix": "⟦身份证"},
    "PHONE":     {"label": "手机号",   "prefix": "⟦手机"},
    "EMAIL":     {"label": "邮箱",     "prefix": "⟦邮箱"},
    "BANK_CARD": {"label": "银行卡",   "prefix": "⟦银行卡"},
    "IP_ADDR":   {"label": "IP地址",   "prefix": "⟦IP"},
    "PRODUCT":   {"label": "产品",     "prefix": "⟦产品"},
    "EVENT":     {"label": "事件",     "prefix": "⟦事件"},
}


class CodebookGenerator:
    """从提取结果生成 codebook 内容"""

    def generate(
        self,
        result: ExtractionResult,
        selected_types: Optional[set[str]] = None,
        auto_replacement: bool = True,
    ) -> str:
        """
        生成 codebook 文本内容。

        Args:
            result: NER 提取结果
            selected_types: 用户选择的实体类型集合；None 表示全部
            auto_replacement: True 则自动生成脱敏词，
                              False 则脱敏词留空（用户在 UI 中填写）
        Returns:
            codebook 格式的文本内容
        """
        lines: list[str] = []
        lines.append("# DocMask 自动生成的密码本")
        lines.append("# 请检查并修改脱敏词（==> 右侧）后使用")
        lines.append("")

        # 按类型分组并统计
        by_type = result.by_type_with_count()

        for ent_label, entities in sorted(by_type.items()):
            if selected_types and ent_label not in selected_types:
                continue

            config = TYPE_CONFIG.get(ent_label)
            if config is None:
                # 未知类型，使用通用格式
                config = {"label": ent_label, "prefix": f"⟦{ent_label}"}

            lines.append(f"# === {config['label']} ===")

            # 按出现次数降序排列
            sorted_entities = sorted(entities.items(), key=lambda x: -x[1])
            for idx, (text, count) in enumerate(sorted_entities, start=1):
                if auto_replacement:
                    replacement = f"{config['prefix']}-{idx:03d}⟧"
                else:
                    replacement = "待填写"
                lines.append(f"{text}{CODEBOOK_SEPARATOR}{replacement}")

            lines.append("")

        return "\n".join(lines)

    def generate_for_type(
        self,
        result: ExtractionResult,
        ent_label: str,
        auto_replacement: bool = True,
    ) -> list[tuple[str, str]]:
        """
        生成单个类型的 codebook 规则列表。
        返回 [(原文, 脱敏词), ...]，用于 UI 表格填充。
        """
        by_type = result.by_type_with_count()
        entities = by_type.get(ent_label, {})
        config = TYPE_CONFIG.get(ent_label, {"prefix": f"⟦{ent_label}"})

        rules = []
        for idx, (text, count) in enumerate(
            sorted(entities.items(), key=lambda x: -x[1]), start=1
        ):
            if auto_replacement:
                replacement = f"{config['prefix']}-{idx:03d}⟧"
            else:
                replacement = ""
            rules.append((text, replacement))

        return rules
```

### 2.4 自动生成脱敏词

**命名规则：** `⟦类型-序号⟧`

```
张三   ==> ⟦人名-001⟧
李四   ==> ⟦人名-002⟧
某某科技 ==> ⟦组织-001⟧
北京市   ==> ⟦地名-001⟧
```

**选择此格式的理由：**

1. `⟦⟧` 是 Unicode 字符（U+27E6 / U+27E7），在中文文档中几乎不会自然出现，满足现有的冲突预检要求（`precheck_conflict` 会检测脱敏词是否已存在于文档中）
2. 格式结构化，恢复时可明确识别
3. 与现有的 `DESENSITIZED_SUFFIX` 等配置风格一致

**与现有冲突预检的兼容性：**

现有的 `Masker.precheck_conflict()` 会扫描文档全文，检查脱敏词是否已存在。`⟦⟧` 格式在自然文档中不出现，因此能通过预检。无需修改 `masker.py`。

### 2.5 与现有架构集成

**与 `Codebook` 类的集成：**

不需要修改 `Codebook` 类。生成的 codebook 文本直接写入 `.txt` 文件，然后通过现有的 `Codebook.load()` 加载。保持文件作为单一数据源的设计。

```python
# controller.py 中新增的方法（示意）
def smart_extract(self, filepath: str) -> ExtractionResult:
    """从文件提取敏感信息"""
    extractor = EntityExtractor()
    if not extractor.is_available():
        raise RuntimeError("NER 模型未安装，请运行: python -m spacy download zh_core_web_trf")
    return extractor.extract_from_file(filepath)

def generate_codebook(
    self, result: ExtractionResult,
    selected_types: set[str],
    output_path: str,
) -> None:
    """从提取结果生成 codebook 文件"""
    gen = CodebookGenerator()
    content = gen.generate(result, selected_types)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
```

**与 UI 的集成（示意）：**

```
工作台页面新增流程：

1. 用户选择待脱敏文件
2. 点击 [智能预读] 按钮
3. 后台线程调用 EntityExtractor.extract_from_file()
4. 提取完成，弹窗展示：
   ┌─────────────────────────────────────────────┐
   │  智能预读结果                                 │
   ├──────────┬──────────┬────────┬─────────────┤
   │ 类型     │ 实体数    │ 去重数  │ 是否纳入     │
   ├──────────┼──────────┼────────┼─────────────┤
   │ 人名     │ 15       │ 8      │ ☑           │
   │ 组织名   │ 6        │ 3      │ ☑           │
   │ 地名     │ 12       │ 5      │ ☑           │
   │ 日期     │ 20       │ 12     │ ☐           │
   │ 身份证   │ 3        │ 3      │ ☑           │
   │ 手机号   │ 5        │ 5      │ ☑           │
   └──────────┴──────────┴────────┴─────────────┘
   │  [生成密码本]  [取消]                        │
   └─────────────────────────────────────────────┘
5. 用户勾选类型 → 点击 [生成密码本]
6. 调用 CodebookGenerator 生成 .txt 文件
7. 自动加载到当前 codebook 状态
```

### 2.6 完整工作流

```
用户选择文件
     │
     ▼
[智能预读] 按钮 ──→ EntityExtractor.extract_from_file()
     │                    │
     │               NER 模型推理
     │                    │
     │               ExtractionResult
     │                    │
     ▼                    ▼
弹窗展示提取结果    用户在 UI 中：
(按类型分组统计)    1. 勾选要纳入的类型
                    2. 查看每个实体（可选）
                    3. 删除不需要的实体（可选）
                         │
                         ▼
                 CodebookGenerator.generate()
                         │
                    生成 codebook.txt
                         │
                    ┌────┴────┐
                    ▼         ▼
              自动加载     用户编辑
              到当前状态    (功能3: UI编辑器)
                    │         │
                    └────┬────┘
                         ▼
                    正常执行脱敏流程
                  (现有流程不变)
```

### 2.7 性能估算

| 文档规模 | 文本量 | spaCy trf 推理 | spaCy sm 推理 |
|---------|--------|---------------|--------------|
| 1 页 (500字) | ~500 字符 | <1 秒 | <0.1 秒 |
| 10 页 | ~5,000 字符 | 2-5 秒 | <1 秒 |
| 50 页 | ~25,000 字符 | 10-25 秒 | 3-5 秒 |
| 100 页 | ~50,000 字符 | 20-50 秒 | 6-10 秒 |

**内存占用：** spaCy trf 模型常驻内存约 500 MB，推理时额外增加 200-500 MB（取决于文本量）。spaCy sm 模型常驻约 50 MB。

---

## 3. 功能二：脱敏后泄密风险检测

### 3.1 风险模型定义

| 风险等级 | 分值 | 含义 | 示例 |
|---------|------|------|------|
| 严重 | 10 | 残留明确敏感实体 | 脱敏后文档中仍有未脱敏的人名 |
| 高 | 7 | 残留格式化敏感信息 | 身份证号/手机号/银行卡号未被正则覆盖 |
| 中 | 4 | 上下文可推断 | "张**在**公司任CEO" → 职务+行业可缩小范围 |
| 低 | 2 | 统计特征泄露 | 具体数值范围（如"营收1.234亿"）可辅助识别 |
| 提示 | 1 | 密码本覆盖不足 | 某些 NER 识别到的实体未被密码本收录 |

**泄密指数 = 所有风险项分值之和。** 指数越高风险越大。

| 泄密指数 | 风险等级 | 建议 |
|---------|---------|------|
| 0 | 安全 | 可直接分发 |
| 1-5 | 低风险 | 建议人工复核 |
| 6-15 | 中风险 | 必须人工复核后再分发 |
| 16+ | 高风险 | 禁止分发，需补充脱敏 |

### 3.2 检测层级设计

```
脱敏后文档
    │
    ├── 第一层：规则扫描（快速，零额外依赖）
    │   │
    │   ├── 1a. 残留 NER 实体检测
    │   │   └── 对脱敏后文档再次运行 NER，检查是否仍有敏感实体
    │   │       （与功能一共享模型）
    │   │
    │   ├── 1b. 残留格式化信息检测
    │   │   └── 正则扫描：身份证、手机、邮箱、银行卡、IP 等
    │   │       （复用现有的 EXTENDED_PATTERNS）
    │   │
    │   ├── 1c. 密码本覆盖率分析
    │   │   └── 检查密码本中哪些规则未命中（可能规则有误或文档已无对应内容）
    │   │       （复用现有的 generate_coverage_report 逻辑）
    │   │
    │   └── 1d. 脱敏词残留检测
    │       └── 检查脱敏后文档中脱敏词是否出现在异常位置
    │           （如脱敏词出现在引号内、或连续出现多个脱敏词）
    │
    ├── 第二层：LLM 语义审查（可选，需额外安装 Ollama）
    │   │
    │   └── 提示 LLM 检查上下文推断风险
    │       "以下文档已脱敏，检查是否仍有可通过上下文
    │        推断身份的信息"
    │
    └── 输出：RiskReport
        ├── 总泄密指数
        ├── 各层级详细发现
        └── 建议操作
```

### 3.3 模块设计

```
docmask/
├── analysis/
│   ├── __init__.py
│   ├── entity.py                 # 功能一已定义
│   ├── extractor.py              # 功能一已定义
│   ├── codebook_generator.py     # 功能一已定义
│   ├── model_loader.py           # 功能一已定义
│   ├── auditor.py                # 新增：泄密风险检测器
│   └── risk_rules.py             # 新增：规则扫描的正则规则
├── core/
│   └── masker.py                 # 现有，不改动
```

**`risk_rules.py` — 规则扫描的正则规则：**

```python
"""风险检测的正则规则集合"""
import re

# 格式化敏感信息检测规则
# (规则名, 正则, 风险等级, 风险分值, 描述)
FORMAT_RISK_RULES: list[tuple[str, re.Pattern, str, int, str]] = [
    (
        "身份证号残留",
        re.compile(r"\d{17}[\dXx]"),
        "高", 7,
        "文档中可能残留未脱敏的身份证号码",
    ),
    (
        "手机号残留",
        re.compile(r"1[3-9]\d{9}"),
        "高", 7,
        "文档中可能残留未脱敏的手机号码",
    ),
    (
        "邮箱地址残留",
        re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"),
        "高", 7,
        "文档中可能残留未脱敏的邮箱地址",
    ),
    (
        "银行卡号残留",
        re.compile(r"\d{16,19}"),
        "中", 4,
        "文档中可能残留未脱敏的银行卡号（也可能为普通数字）",
    ),
    (
        "IP地址残留",
        re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"),
        "中", 4,
        "文档中可能残留未脱敏的IP地址",
    ),
]
```

**`auditor.py` — 泄密风险检测器：**

```python
"""泄密风险检测器：脱敏后文档的安全审计"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from docmask.analysis.extractor import EntityExtractor, ExtractionResult
from docmask.analysis.risk_rules import FORMAT_RISK_RULES
from docmask.analysis.codebook_generator import TYPE_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class RiskFinding:
    """单项风险发现"""
    level: str          # 严重 / 高 / 中 / 低 / 提示
    score: int          # 风险分值
    category: str       # 风险类别
    description: str    # 风险描述
    evidence: str       # 风险证据（截取的文本片段）
    location: str       # 位置信息


@dataclass
class RiskReport:
    """泄密风险报告"""
    findings: list[RiskFinding] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        """总泄密指数"""
        return sum(f.score for f in self.findings)

    @property
    def risk_level(self) -> str:
        """风险等级"""
        score = self.total_score
        if score == 0:
            return "安全"
        elif score <= 5:
            return "低风险"
        elif score <= 15:
            return "中风险"
        else:
            return "高风险"

    @property
    def is_safe(self) -> bool:
        """是否安全（可直接分发）"""
        return self.total_score == 0

    @property
    def needs_review(self) -> bool:
        """是否需要人工复核"""
        return self.total_score > 0

    def by_level(self) -> dict[str, list[RiskFinding]]:
        """按风险等级分组"""
        groups: dict[str, list[RiskFinding]] = {}
        for f in self.findings:
            groups.setdefault(f.level, []).append(f)
        return groups

    def summary(self) -> str:
        """生成可读的摘要文本"""
        lines = []
        lines.append("=" * 50)
        lines.append("泄密风险检测报告")
        lines.append("=" * 50)
        lines.append(f"总泄密指数: {self.total_score}")
        lines.append(f"风险等级: {self.risk_level}")
        lines.append("")

        if not self.findings:
            lines.append("未发现泄密风险，文档可安全分发。")
        else:
            by_level = self.by_level()
            for level in ["严重", "高", "中", "低", "提示"]:
                if level in by_level:
                    lines.append(f"【{level}】({len(by_level[level])} 项)")
                    for f in by_level[level]:
                        lines.append(f"  - {f.description}")
                        if f.evidence:
                            lines.append(f"    证据: ...{f.evidence}...")
                        if f.location:
                            lines.append(f"    位置: {f.location}")
                    lines.append("")

        lines.append("=" * 50)
        return "\n".join(lines)


class RiskAuditor:
    """泄密风险检测器"""

    def __init__(self):
        self._extractor = EntityExtractor()

    def is_available(self) -> bool:
        """检查 NER 模型是否可用（第一层 1a 需要）"""
        return self._extractor.is_available()

    def audit(
        self,
        masked_text: str,
        codebook_originals: set[str],
        codebook_replacements: set[str],
        coverage_report: Optional[dict[str, int]] = None,
    ) -> RiskReport:
        """
        对脱敏后文档执行泄密风险检测。

        Args:
            masked_text: 脱敏后的文档全文
            codebook_originals: 密码本中所有原文的集合
            codebook_replacements: 密码本中所有脱敏词的集合
            coverage_report: 脱敏覆盖率报告（原文 → 命中次数）
        Returns:
            RiskReport 风险报告
        """
        report = RiskReport()

        # 第一层：规则扫描
        self._check_residual_entities(masked_text, report)
        self._check_format_patterns(masked_text, report)
        self._check_coverage(codebook_originals, coverage_report, report)
        self._check_replacement_anomalies(masked_text, codebook_replacements, report)

        return report

    def _check_residual_entities(self, text: str, report: RiskReport) -> None:
        """第一层 1a：残留 NER 实体检测"""
        if not self._extractor.is_available():
            return

        result = self._extractor.extract(text)
        by_type = result.by_type_with_count()

        for ent_label, entities in by_type.items():
            config = TYPE_CONFIG.get(ent_label, {"label": ent_label})
            label = config["label"]

            for text_str, count in entities.items():
                # 过滤掉过短的实体（单字可能是误报）
                if len(text_str) < 2:
                    continue

                report.findings.append(RiskFinding(
                    level="严重",
                    score=10,
                    category="残留敏感实体",
                    description=f"脱敏后文档中仍检测到{label}: \"{text_str}\" (出现{count}次)",
                    evidence=text_str[:50],
                    location=f"NER标签={ent_label}",
                ))

    def _check_format_patterns(self, text: str, report: RiskReport) -> None:
        """第一层 1b：残留格式化敏感信息检测"""
        for name, pattern, level, score, desc in FORMAT_RISK_RULES:
            matches = pattern.findall(text)
            if matches:
                report.findings.append(RiskFinding(
                    level=level,
                    score=score,
                    category="格式化信息残留",
                    description=f"{name}: {desc} (发现{len(matches)}处)",
                    evidence=str(matches[:3]),  # 最多展示3个
                    location=f"正则={pattern.pattern}",
                ))

    def _check_coverage(
        self,
        originals: set[str],
        coverage: Optional[dict[str, int]],
        report: RiskReport,
    ) -> None:
        """第一层 1c：密码本覆盖率分析"""
        if coverage is None:
            return

        unmatched = [k for k, v in coverage.items() if v == 0]
        if unmatched:
            report.findings.append(RiskFinding(
                level="提示",
                score=1,
                category="密码本覆盖不足",
                description=f"密码本中有 {len(unmatched)} 条规则未命中任何文本，"
                           f"可能存在遗漏的敏感信息",
                evidence=str(unmatched[:5]),
                location="覆盖率报告",
            ))

    def _check_replacement_anomalies(
        self,
        text: str,
        replacements: set[str],
        report: RiskReport,
    ) -> None:
        """第一层 1d：脱敏词异常使用检测"""
        for rep in replacements:
            if not rep:
                continue
            # 检查脱敏词是否出现在引号内（可能泄露脱敏机制）
            quoted_pattern = re.compile(
                rf'["""\'《].*?{re.escape(rep)}.*?["""\'》]'
            )
            if quoted_pattern.search(text):
                report.findings.append(RiskFinding(
                    level="低",
                    score=2,
                    category="脱敏词异常使用",
                    description=f"脱敏词 '{rep}' 出现在引号内，可能暴露脱敏行为",
                    evidence=rep,
                    location="引号内",
                ))

            # 检查连续出现多个相同脱敏词（可能泄露实体数量）
            consecutive = re.compile(
                rf"{re.escape(rep)}[\s，,。、]*{re.escape(rep)}"
            )
            if consecutive.search(text):
                report.findings.append(RiskFinding(
                    level="低",
                    score=2,
                    category="脱敏词异常使用",
                    description=f"脱敏词 '{rep}' 连续出现，可能泄露同一实体的多次出现",
                    evidence=rep,
                    location="连续出现",
                ))
```

### 3.4 与现有架构集成

**集成点：脱敏完成后触发风险检测**

现有的脱敏流程在 `handler.mask()` 返回后即结束。新增的风险检测作为**可选的后处理步骤**，在 controller 层调用，不改动 handler 代码：

```python
# controller.py 中 _run_task 方法修改示意（仅展示新增部分）

def _run_task(self, on_file_start, on_file_done, on_progress, on_complete):
    # ... 现有代码 ...

    for i, item in enumerate(results):
        # ... 现有脱敏逻辑 ...

        if mode == Mode.MASK:
            output_path, count, coverage = handler.mask(...)

            # ===== 新增：脱敏后风险检测（可选） =====
            if self.state.enable_risk_audit:
                try:
                    auditor = RiskAuditor()
                    # 读取脱敏后文档全文
                    masked_text = self._read_file_text(output_path)
                    # 获取密码本原文和脱敏词集合
                    originals = set(state.codebook.codebook.forward_map.keys())
                    replacements = set(state.codebook.codebook.forward_map.values())

                    risk_report = auditor.audit(
                        masked_text, originals, replacements, coverage
                    )
                    item.risk_report = risk_report  # 新增字段

                    if risk_report.total_score > 15:
                        logger.warning(
                            f"高风险: {item.filename} 泄密指数={risk_report.total_score}"
                        )
                except Exception as e:
                    logger.warning(f"风险检测失败: {e}")
            # =========================================

        # ... 现有后续逻辑 ...
```

**在 `state.py` 中新增状态字段：**

```python
@dataclass
class FileItem:
    # ... 现有字段 ...
    risk_report: Optional["RiskReport"] = None  # 脱敏后风险报告

@dataclass
class AppState:
    # ... 现有字段 ...
    enable_risk_audit: bool = True  # 是否启用脱敏后风险检测
```

### 3.5 完整工作流

```
脱敏任务完成
     │
     ▼
读取脱敏后文档全文
     │
     ▼
RiskAuditor.audit()
     │
     ├── 第一层 1a: NER 残留实体检测
     │   └── 对脱敏后文本运行 NER，检查是否仍有敏感实体
     │       （与功能一共享 spaCy 模型）
     │
     ├── 第一层 1b: 格式化信息残留检测
     │   └── 正则扫描身份证/手机/邮箱/银行卡/IP
     │       （复用 EXTENDED_PATTERNS 中的正则）
     │
     ├── 第一层 1c: 密码本覆盖率分析
     │   └── 检查未命中的规则（复用现有 coverage 数据）
     │
     ├── 第一层 1d: 脱敏词异常使用检测
     │   └── 检查脱敏词是否在引号内/连续出现
     │
     └── （可选）第二层: LLM 语义审查
         └── 调用本地 Ollama，提示词审查上下文推断风险
     │
     ▼
RiskReport
     │
     ├── 总泄密指数 + 风险等级
     ├── 各层级详细发现列表
     └── 可读摘要文本
     │
     ▼
UI 展示风险报告
     │
     ├── 绿色（安全）: 可直接分发
     ├── 黄色（低风险）: 建议人工复核
     ├── 橙色（中风险）: 必须人工复核
     └── 红色（高风险）: 禁止分发
```

### 3.6 性能估算

| 检测层 | 耗时 | 依赖 |
|--------|------|------|
| 1a NER 残留实体 | 2-5 秒/10页 | spaCy 模型（与功能一共享） |
| 1b 格式化信息正则 | <0.1 秒 | 无 |
| 1c 覆盖率分析 | <0.01 秒 | 无（复用现有数据） |
| 1d 脱敏词异常检测 | <0.1 秒 | 无 |
| **第一层合计** | **2-5 秒** | **spaCy（可选）** |
| 2 LLM 语义审查 | 30-120 秒 | Ollama + 本地 LLM（可选） |

**第一层（规则扫描）已经能覆盖约 80% 的泄密场景，且成本极低（与脱敏共享 NER 模型）。第二层作为可选增强，默认关闭。**

---

## 4. 依赖与体积影响

### 4.1 新增 Python 依赖

```
# requirements_ai.txt（可选 AI 模块依赖，独立文件）
spacy>=3.7.0
# 模型需单独下载：
#   python -m spacy download zh_core_web_trf   # 高精度（450 MB）
#   python -m spacy download zh_core_web_sm     # 轻量（30 MB）
```

### 4.2 体积影响

| 组件 | 体积 | 说明 |
|------|------|------|
| 当前应用（docmask-cli.exe） | 16 MB | 纯规则脱敏 |
| + spaCy 框架 | +50 MB | Python 库本身 |
| + zh_core_web_sm 模型 | +30 MB | 轻量 NER |
| + zh_core_web_trf 模型 | +450 MB | 高精度 NER |
| **AI 增强版总计** | **~500 MB** | 含高精度模型 |
| **AI 轻量版总计** | **~100 MB** | 含轻量模型 |

### 4.3 降级策略

```python
# 依赖检测与降级逻辑
def check_ai_capability() -> str:
    """检测 AI 模块可用性，返回能力等级"""
    try:
        import spacy
        try:
            spacy.load("zh_core_web_trf")
            return "full"       # 高精度模型可用
        except OSError:
            try:
                spacy.load("zh_core_web_sm")
                return "lite"   # 轻量模型可用
            except OSError:
                return "none"   # spaCy 已安装但模型未下载
    except ImportError:
        return "none"           # spaCy 未安装
```

| 能力等级 | 智能预读（功能一） | 风险检测（功能二） |
|---------|:----------------:|:----------------:|
| `full` | NER 提取（85%+ 准确率） | NER 残留检测 + 正则扫描 |
| `lite` | NER 提取（70% 准确率） | NER 残留检测 + 正则扫描 |
| `none` | 不可用，按钮灰显 | 仅正则扫描（跳过 1a） |

---

## 5. 打包策略

### 5.1 三种打包配置

| 版本 | 包含内容 | 体积 | 适用场景 |
|------|---------|------|---------|
| **标准版** | 纯规则脱敏 + UI | ~20 MB | 不需要 AI 功能的用户 |
| **AI 轻量版** | 标准版 + spaCy + sm 模型 | ~100 MB | 需要 AI 功能，对体积敏感 |
| **AI 完整版** | 标准版 + spaCy + trf 模型 | ~500 MB | 需要 AI 功能，追求准确率 |

### 5.2 PyInstaller 打包命令

```bash
# 标准版（现有）
pyinstaller --onefile --windowed --name docmask-ui docmask_ui.py

# AI 轻量版
pyinstaller --onefile --windowed --name docmask-ui-ai \
  --add-data "path/to/zh_core_web_sm;zh_core_web_sm" \
  --hidden-import spacy \
  --hidden-import thinc \
  docmask_ui.py

# AI 完整版
pyinstaller --onefile --windowed --name docmask-ui-ai-pro \
  --add-data "path/to/zh_core_web_trf;zh_core_web_trf" \
  --hidden-import spacy \
  --hidden-import thinc \
  --hidden-import torch \
  docmask_ui.py
```

### 5.3 模型独立分发

模型文件不打包进 exe，而是在首次使用时提示用户安装：

```
首次点击 [智能预读] 时:
  → 检测到 spaCy 模型未安装
  → 弹窗提示："智能预读需要下载中文 NER 模型（约 450 MB），是否下载？"
  → 用户确认后执行: python -m spacy download zh_core_web_trf
  → 下载完成后自动重试
```

---

## 6. 配置项设计

```python
# config.py 新增常量

# === AI 辅助功能配置 ===

# NER 模型优先级（从高到低尝试加载）
NER_MODEL_PREFERRED = "zh_core_web_trf"
NER_MODEL_FALLBACK = "zh_core_web_sm"

# NER 提取时每批处理的最大字符数
NER_BATCH_SIZE = 5000

# 风险检测默认开关
RISK_AUDIT_ENABLED = True

# 风险检测阈值
RISK_THRESHOLD_LOW = 5       # 0-5: 低风险
RISK_THRESHOLD_MEDIUM = 15    # 6-15: 中风险
                              # 16+: 高风险

# 残留实体最小长度（过滤误报）
MIN_ENTITY_LENGTH = 2

# 脱敏词格式
MASK_PREFIX_L = "⟦"
MASK_SUFFIX_R = "⟧"
```

---

## 7. 里程碑与实施顺序

### 7.1 依赖关系

```
功能三（UI 编辑 codebook）
    │
    │ 功能一的 NER 结果需要填入 UI 表格
    │ 功能三提供编辑界面
    ▼
功能一（智能预读）
    │
    │ 功能二的残留检测复用功能一的 NER 模型
    ▼
功能二（泄密检测）
    │
    │ 第一层（规则扫描）可与功能一一起做
    │ 第二层（LLM 审查）延后
    ▼
（可选）LLM 语义审查
```

### 7.2 里程碑

| 里程碑 | 内容 | 依赖 |
|--------|------|------|
| M-AI-1 | `analysis/` 包骨架 + `model_loader.py` + `entity.py` | 无 |
| M-AI-2 | `extractor.py` + `codebook_generator.py` | M-AI-1 |
| M-AI-3 | UI 集成：智能预读按钮 + 结果弹窗 | M-AI-2 + 功能三 |
| M-AI-4 | `risk_rules.py` + `auditor.py`（第一层） | M-AI-1（共享模型） |
| M-AI-5 | UI 集成：风险报告展示 | M-AI-4 |
| M-AI-6 | 测试：`tests/test_extractor.py` + `tests/test_auditor.py` | M-AI-2, M-AI-4 |
| M-AI-7 | 打包配置（三版本） + 文档更新 | M-AI-3, M-AI-5 |
| M-AI-8 | （可选）LLM 语义审查层 | M-AI-5 |

### 7.3 建议优先级

```
优先做：功能三（UI 编辑 codebook）  ← 无外部依赖，基础设施
其次做：功能一（智能预读）          ← 与功能三联动效果好
再  做：功能二第一层（规则扫描）     ← 与功能一共享模型
延  后：功能二第二层（LLM 审查）     ← 重依赖，可选增强
```
