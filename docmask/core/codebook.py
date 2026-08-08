"""密码本解析与校验模块"""
import os
import re

# A-02 ReDoS 防护：优先使用支持 timeout 的 regex 模块，回退到标准 re。
# 有 regex 模块时，每条正则在编译时绑定超时，finditer/search 自动受限；
# 无 regex 模块时，仅靠输入长度限制提供部分防护。
try:
    import regex as _re_mod
    _HAS_REGEX_MODULE = True
    _REGEX_TIMEOUT_SECONDS = 2.0
except ImportError:
    import re as _re_mod
    _HAS_REGEX_MODULE = False
    _REGEX_TIMEOUT_SECONDS = None

from docmask.config import CODEBOOK_SEPARATOR, REGEX_PREFIX, COMMENT_PREFIX


class CodebookError(Exception):
    """密码本相关错误"""

    pass


class Codebook:
    """密码本：加载、解析、校验"""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.forward_map: dict[str, str] = {}  # 原文 → 脱敏词
        self.reverse_map: dict[str, str] = {}  # 脱敏词 → 原文
        self._sorted_keys: list[str] = []  # 按长度降序排列的原文列表（精确规则）
        self.regex_rules: list[tuple[re.Pattern, str]] = []  # (编译后正则, 脱敏词)
        self._line_numbers: dict[str, int] = {}  # 规则原文 → 行号（用于错误提示）
        self._regex_line_numbers: list[int] = []

    def load(self) -> None:
        """读取并解析密码本文件，自动检测编码"""
        if not os.path.exists(self.filepath):
            raise CodebookError(f"密码本文件未找到：{self.filepath}")

        # 尝试多种编码读取
        content = None
        for encoding in ["utf-8", "utf-8-sig", "gbk", "gb2312"]:
            try:
                with open(self.filepath, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if content is None:
            raise CodebookError(
                f"无法识别密码本文件编码，请使用 UTF-8 编码保存：{self.filepath}"
            )

        self._parse(content)

    def _parse(self, content: str) -> None:
        """解析密码本内容"""
        self.forward_map.clear()
        self.reverse_map.clear()
        self._sorted_keys.clear()
        self.regex_rules.clear()
        self._line_numbers.clear()
        self._regex_line_numbers.clear()

        lines = content.splitlines()
        seen_rules: dict[str, int] = {}

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()

            # 跳过空行和注释
            if not line or line.startswith(COMMENT_PREFIX):
                continue

            # 检查分隔符
            if CODEBOOK_SEPARATOR not in line:
                raise CodebookError(
                    f"密码本第 {line_num} 行格式错误，缺少分隔符 '==>'：{raw_line}"
                )

            parts = line.split(CODEBOOK_SEPARATOR, 1)
            original = parts[0].strip()
            replacement = parts[1].strip()

            # 原文和脱敏词不可为空
            if not original:
                raise CodebookError(f"密码本第 {line_num} 行原文为空：{raw_line}")
            if not replacement:
                raise CodebookError(f"密码本第 {line_num} 行脱敏词为空：{raw_line}")

            # 正则规则
            if original.startswith(REGEX_PREFIX):
                pattern_str = original[len(REGEX_PREFIX):]
                rule_key = f"{REGEX_PREFIX}{pattern_str}"
                if rule_key in seen_rules:
                    raise CodebookError(
                        f"密码本第 {line_num} 行重复定义原文；首次定义在第 "
                        f"{seen_rules[rule_key]} 行：{rule_key}"
                    )
                try:
                    compiled = _re_mod.compile(pattern_str)
                except _re_mod.error as e:
                    raise CodebookError(
                        f"密码本第 {line_num} 行正则表达式无效：{pattern_str}，错误：{e}"
                    )
                if compiled.search("") is not None:
                    raise CodebookError(
                        f"密码本第 {line_num} 行正则表达式可匹配空字符串，"
                        "该规则会产生不确定替换，已拒绝加载"
                    )
                seen_rules[rule_key] = line_num
                self.regex_rules.append((compiled, replacement))
                self._regex_line_numbers.append(line_num)
                continue

            # 精确匹配规则
            # 原文==脱敏词 相同 → WARNING（在 validate 中处理）
            # 重复定义检测
            if original in seen_rules:
                raise CodebookError(
                    f"密码本第 {line_num} 行重复定义原文；首次定义在第 "
                    f"{seen_rules[original]} 行：{original}"
                )

            seen_rules[original] = line_num
            self.forward_map[original] = replacement
            self._line_numbers[original] = line_num

        # 构建逆向映射表
        for original, replacement in self.forward_map.items():
            self.reverse_map[replacement] = original

        # 按长度降序排列原文（用于最长匹配）
        self._sorted_keys = sorted(
            self.forward_map.keys(), key=lambda k: len(k), reverse=True
        )

    def validate(self) -> list[str]:
        """
        校验密码本合法性，返回警告/错误信息列表。
        每条消息格式: "LEVEL: 消息内容"
        """
        messages: list[str] = []

        # 空密码本检测
        if not self.forward_map and not self.regex_rules:
            messages.append("ERROR: 密码本为空，未包含任何有效规则")
            return messages

        # 1. 所有精确/正则规则的脱敏词必须全局唯一。
        seen_replacements: dict[str, str] = {}
        for original, replacement in self.forward_map.items():
            if replacement in seen_replacements:
                other_original = seen_replacements[replacement]
                messages.append(
                    f"ERROR: 脱敏词重复 —— '{original}' 和 '{other_original}' "
                    f"都映射到 '{replacement}'，恢复时会产生歧义"
                )
            else:
                seen_replacements[replacement] = original

        for index, (pattern, replacement) in enumerate(self.regex_rules, start=1):
            rule_name = f"regex:{pattern.pattern}"
            if replacement in seen_replacements:
                messages.append(
                    f"ERROR: 脱敏词重复 —— '{rule_name}' 和 "
                    f"'{seen_replacements[replacement]}' 都映射到 '{replacement}'，"
                    "无法唯一识别规则来源"
                )
            else:
                seen_replacements[replacement] = rule_name

        # 2. 原文与脱敏词相同
        for original, replacement in self.forward_map.items():
            if original == replacement:
                messages.append(
                    f"WARNING: 原文与脱敏词相同 —— '{original}==>{replacement}'，"
                    f"此规则无意义"
                )

        # 3. 交叉冲突检测：任何脱敏词不得出现在其他精确规则的原文中
        all_originals = set(self.forward_map.keys())
        for original, replacement in self.forward_map.items():
            if replacement in all_originals:
                line = self._line_numbers.get(original, "?")
                messages.append(
                    f"ERROR: 交叉冲突 —— 第 {line} 行规则 '{original}==>{replacement}' "
                    f"的脱敏词 '{replacement}' 是另一条规则的原文，"
                    f"脱敏时可能被二次替换，导致恢复失败"
                )

        # 4. 正则规则脱敏词与精确规则原文冲突会破坏规则边界。
        for pattern, replacement in self.regex_rules:
            if replacement in all_originals:
                messages.append(
                    f"ERROR: 正则规则脱敏词 '{replacement}' 是另一条精确规则的原文，"
                    "会导致恢复语义不唯一"
                )

        return messages

    def validate_reversibility(self, text: str) -> list[str]:
        """校验当前文档是否满足可逆处理前置条件。

        结构校验由 :meth:`validate` 负责；本方法只检查与文档内容有关的
        冲突。正则替换本身不保存原始匹配值，因此会明确标记为不可逆。
        """
        messages: list[str] = []
        for replacement in dict.fromkeys(
            list(self.forward_map.values())
            + [replacement for _, replacement in self.regex_rules]
        ):
            count = text.count(replacement)
            if count:
                messages.append(
                    f"ERROR: 文档中已存在脱敏词（出现 {count} 次），无法区分原文与脱敏结果"
                )
        if any(pattern.search(text) for pattern, _ in self.regex_rules):
            messages.append(
                "WARNING: 文档命中了正则规则；正则规则不保存原始匹配值，不能保证 restore 还原"
            )
        return messages

    def get_forward_map(self) -> dict[str, str]:
        """获取正向映射表（原文 → 脱敏词）"""
        return dict(self.forward_map)

    def get_reverse_map(self) -> dict[str, str]:
        """获取逆向映射表（脱敏词 → 原文）"""
        return dict(self.reverse_map)

    def get_sorted_keys(self) -> list[str]:
        """获取按长度降序排列的原文列表（用于最长匹配）"""
        return list(self._sorted_keys)

    def get_regex_rules(self) -> list[tuple[re.Pattern, str]]:
        """获取正则规则列表"""
        return list(self.regex_rules)

    def get_regex_line_numbers(self) -> list[int]:
        """获取正则规则对应的密码本行号列表（用于 ReDoS 超时错误报告）。"""
        return list(self._regex_line_numbers)

    @property
    def exact_rule_count(self) -> int:
        """精确匹配规则数量"""
        return len(self.forward_map)

    @property
    def regex_rule_count(self) -> int:
        """正则规则数量"""
        return len(self.regex_rules)
