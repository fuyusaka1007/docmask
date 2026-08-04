"""恢复引擎：将脱敏文档恢复为原文"""
import re
import logging
from typing import Optional

from docmask.core.codebook import Codebook

logger = logging.getLogger(__name__)


class Restorer:
    """恢复引擎：将脱敏文档恢复为原文"""

    def __init__(self, codebook: Codebook):
        self.codebook = codebook
        self._reverse_pattern: Optional[re.Pattern] = None
        self._sorted_reverse_keys: list[str] = []

    def _build_reverse_pattern(self) -> None:
        """构建逆向匹配的组合正则表达式"""
        reverse_map = self.codebook.get_reverse_map()
        if not reverse_map:
            self._reverse_pattern = None
            return

        # 脱敏词按长度降序排列（用于最长匹配）
        self._sorted_reverse_keys = sorted(
            reverse_map.keys(), key=lambda k: len(k), reverse=True
        )
        escaped = [re.escape(k) for k in self._sorted_reverse_keys]
        self._reverse_pattern = re.compile("|".join(escaped))

    def restore_text(self, text: str) -> tuple[str, int]:
        """
        对纯文本执行恢复（一次遍历，已替换部分不再参与后续匹配）
        返回 (恢复后文本, 替换次数)
        注意：仅恢复精确匹配规则，正则规则不可逆
        """
        reverse_map = self.codebook.get_reverse_map()
        if not reverse_map:
            return text, 0

        if self._reverse_pattern is None:
            self._build_reverse_pattern()

        count = 0

        def _replace(match):
            nonlocal count
            matched_text = match.group(0)
            original = reverse_map[matched_text]
            count += 1
            return original

        result = self._reverse_pattern.sub(_replace, text)
        return result, count