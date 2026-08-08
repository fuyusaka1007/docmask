"""脱敏引擎：执行文本脱敏，支持一次遍历+最长匹配策略"""
import re
import logging
from typing import Optional

from docmask.core.codebook import Codebook, _HAS_REGEX_MODULE, _REGEX_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# A-02: 正则规则输入长度硬限制（字节）。超过此长度的文本块只对精确规则全文匹配，
# 正则规则仅匹配前 _MAX_REGEX_INPUT_LENGTH 字符。无 regex 模块时这是主要 ReDoS 防线。
_MAX_REGEX_INPUT_LENGTH = 256 * 1024  # 256 KB

# regex 模块的 finditer 在超时时抛出内置 TimeoutError；无 regex 模块时占位异常永远不会触发。
if _HAS_REGEX_MODULE:
    _REGEX_TIMEOUT_ERROR = TimeoutError
else:
    _REGEX_TIMEOUT_ERROR = type("_NeverRaised", (BaseException,), {})


class RegexBudgetExceededError(Exception):
    """正则规则执行超预算（ReDoS 防护触发）。"""

    def __init__(self, rule_index: int, line_number: Optional[int] = None):
        self.rule_index = rule_index
        self.line_number = line_number
        msg = f"正则规则执行超时（规则索引 {rule_index}"
        if line_number is not None:
            msg += f"，密码本第 {line_number} 行"
        msg += "），已中止该文件处理"
        super().__init__(msg)


class MaskConflictError(Exception):
    """脱敏词冲突错误：脱敏词已存在于原文档中，继续处理会导致恢复时无法区分"""

    @staticmethod
    def format(conflicts: list[tuple[str, int]]) -> str:
        """将冲突列表格式化为可读的错误消息"""
        lines = ["文档中已存在脱敏词，继续处理将导致恢复时无法区分原始字符和脱敏结果："]
        for word, count in conflicts:
            lines.append(f"  脱敏词 '{word}' 已在原文档中出现 {count} 次")
        lines.append("请更换冲突的脱敏词后重试。")
        return "\n".join(lines)


class Masker:
    """脱敏引擎：执行文本/文档脱敏"""

    def __init__(self, codebook: Codebook):
        self.codebook = codebook
        self._exact_pattern: Optional[re.Pattern] = None  # 精确匹配组合正则
        self._hit_counts: dict[str, int] = {}  # 原文 → 命中次数

    def _build_exact_pattern(self) -> None:
        """构建精确匹配的组合正则表达式"""
        keys = self.codebook.get_sorted_keys()
        if not keys:
            self._exact_pattern = None
            return

        # 按长度降序排列，正则交替从左到右匹配，保证最长匹配优先
        escaped = [re.escape(k) for k in keys]
        pattern_str = "|".join(escaped)
        self._exact_pattern = re.compile(pattern_str)

    def precheck_conflict(self, text: str) -> list[tuple[str, int]]:
        """
        预检：检查脱敏词是否已存在于文本中。
        返回冲突列表 [(脱敏词, 出现次数), ...]，为空表示无冲突。
        """
        conflicts = []
        checked = set()

        # 精确规则的脱敏词
        for replacement in self.codebook.forward_map.values():
            if replacement and replacement not in checked:
                checked.add(replacement)
                if replacement in text:
                    conflicts.append((replacement, text.count(replacement)))

        # 正则规则的脱敏词
        for _, replacement in self.codebook.regex_rules:
            if replacement and replacement not in checked:
                checked.add(replacement)
                if replacement in text:
                    conflicts.append((replacement, text.count(replacement)))

        return conflicts

    def mask_text(self, text: str) -> tuple[str, int, dict[str, int]]:
        """
        对纯文本执行脱敏（一次遍历，已替换部分不再参与后续匹配）
        返回 (脱敏后文本, 总替换次数, 覆盖率统计dict)
        """
        self._hit_counts.clear()
        if not text:
            return text, 0, {}

        # 所有候选都从同一份原文生成，替换结果永远不会进入后续匹配。
        # 排序策略：左端点优先、同起点最长优先、同长度精确规则优先。
        candidates: list[tuple[int, int, int, int, str, str]] = []
        if self.codebook.exact_rule_count:
            if self._exact_pattern is None:
                self._build_exact_pattern()
            if self._exact_pattern is not None:
                for match in self._exact_pattern.finditer(text):
                    key = match.group(0)
                    candidates.append(
                        (match.start(), match.end(), 0, 0, key,
                         self.codebook.forward_map[key])
                    )

        for rule_index, (pattern, replacement) in enumerate(self.regex_rules):
            # A-02: 限制正则输入长度，防止超长文本加剧回溯
            regex_text = text if len(text) <= _MAX_REGEX_INPUT_LENGTH else text[:_MAX_REGEX_INPUT_LENGTH]
            try:
                # regex 模块支持 per-call timeout；re 模块不支持
                if _HAS_REGEX_MODULE:
                    match_iter = pattern.finditer(regex_text, timeout=_REGEX_TIMEOUT_SECONDS)
                else:
                    match_iter = pattern.finditer(regex_text)
                # finditer 返回惰性迭代器，超时在迭代期间抛出，需包裹整个循环
                for match in match_iter:
                    # Codebook 已拒绝空匹配；这里保留防御性检查。
                    if match.end() == match.start():
                        continue
                    key = f"regex:{pattern.pattern}"
                    candidates.append(
                        (match.start(), match.end(), 1, rule_index, key, replacement)
                    )
            except _REGEX_TIMEOUT_ERROR:
                line_numbers = self.codebook.get_regex_line_numbers()
                line_num = line_numbers[rule_index] if rule_index < len(line_numbers) else None
                raise RegexBudgetExceededError(rule_index, line_num) from None

        candidates.sort(
            key=lambda item: (item[0], -(item[1] - item[0]), item[2], item[3])
        )
        result_parts: list[str] = []
        cursor = 0
        total_count = 0
        for start, end, _kind, _order, rule_key, replacement in candidates:
            if start < cursor:
                continue
            result_parts.append(text[cursor:start])
            # 直接追加字符串，避免 re.sub 将 \1、\g<...> 解释为反向引用。
            result_parts.append(replacement)
            cursor = end
            total_count += 1
            self._hit_counts[rule_key] = self._hit_counts.get(rule_key, 0) + 1
        result_parts.append(text[cursor:])
        return "".join(result_parts), total_count, dict(self._hit_counts)

    def generate_coverage_report(self, hit_counts: Optional[dict[str, int]] = None) -> str:
        """生成脱敏覆盖率报告：命中规则统计 + 未命中规则列表"""
        if hit_counts is None:
            hit_counts = self._hit_counts

        lines = []
        lines.append("=" * 50)
        lines.append("脱敏覆盖率报告")
        lines.append("=" * 50)

        # 命中规则统计
        exact_hit = 0
        exact_total = self.codebook.exact_rule_count
        for original in self.codebook.get_sorted_keys():
            c = hit_counts.get(original, 0)
            if c > 0:
                exact_hit += 1
                lines.append(f"  [命中] {original} => {self.codebook.forward_map[original]} (×{c})")

        # 正则规则统计
        regex_hit = 0
        regex_total = self.codebook.regex_rule_count
        for pattern, replacement in self.codebook.regex_rules:
            rule_key = f"regex:{pattern.pattern}"
            c = hit_counts.get(rule_key, 0)
            if c > 0:
                regex_hit += 1
                lines.append(f"  [命中] {rule_key} => {replacement} (×{c})")

        # 未命中规则
        lines.append("-" * 50)
        lines.append(f"精确规则命中: {exact_hit}/{exact_total}")
        lines.append(f"正则规则命中: {regex_hit}/{regex_total}")

        # 未命中精确规则
        unmatched = []
        for original in self.codebook.get_sorted_keys():
            if hit_counts.get(original, 0) == 0:
                unmatched.append(f"  {original} => {self.codebook.forward_map[original]}")
        if unmatched:
            lines.append("未命中精确规则:")
            lines.extend(unmatched)

        # 未命中正则规则
        unmatched_regex = []
        for pattern, replacement in self.codebook.regex_rules:
            rule_key = f"regex:{pattern.pattern}"
            if hit_counts.get(rule_key, 0) == 0:
                unmatched_regex.append(f"  {rule_key} => {replacement}")
        if unmatched_regex:
            lines.append("未命中正则规则:")
            lines.extend(unmatched_regex)

        lines.append("=" * 50)
        return "\n".join(lines)

    def generate_coverage_summary(
        self, hit_counts: Optional[dict[str, int]] = None
    ) -> dict:
        """返回不包含原文、替换值或正则内容的隐私安全统计。"""
        if hit_counts is None:
            hit_counts = self._hit_counts

        rules = []
        exact_hit = 0
        for index, original in enumerate(self.codebook.get_sorted_keys(), start=1):
            count = hit_counts.get(original, 0)
            exact_hit += int(count > 0)
            rules.append({"id": f"E{index:03d}", "type": "exact", "count": count})

        regex_hit = 0
        for index, (pattern, _replacement) in enumerate(
            self.codebook.regex_rules, start=1
        ):
            count = hit_counts.get(f"regex:{pattern.pattern}", 0)
            regex_hit += int(count > 0)
            rules.append({"id": f"R{index:03d}", "type": "regex", "count": count})

        return {
            "exact": {"hit": exact_hit, "total": self.codebook.exact_rule_count},
            "regex": {"hit": regex_hit, "total": self.codebook.regex_rule_count},
            "replacement_count": sum(rule["count"] for rule in rules),
            "rules": rules,
        }

    @property
    def regex_rules(self):
        return self.codebook.get_regex_rules()
