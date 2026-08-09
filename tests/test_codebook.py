"""密码本解析模块测试"""
import os
from unittest.mock import patch

import pytest
from docmask.core.codebook import Codebook, CodebookError

DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")


class TestCodebookLoad:
    """测试密码本加载"""

    def test_load_valid(self):
        """正常解析密码本"""
        cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
        cb.load()
        assert cb.exact_rule_count == 6
        assert cb.regex_rule_count == 3
        assert "张三" in cb.forward_map
        assert cb.forward_map["张三"] == "李四"
        assert cb.reverse_map["李四"] == "张三"

    def test_load_nonexistent(self):
        """密码本文件不存在"""
        cb = Codebook("nonexistent_file.txt")
        with pytest.raises(CodebookError, match="未找到"):
            cb.load()

    def test_load_empty(self):
        """空密码本（只有注释和空行）"""
        cb = Codebook(os.path.join(DATA_DIR, "codebook_empty.txt"))
        cb.load()
        assert cb.exact_rule_count == 2

    def test_skip_comments_and_blank_lines(self):
        """跳过注释和空行"""
        cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
        cb.load()
        assert "#" not in cb.forward_map
        assert "" not in cb.forward_map

    def test_sorted_keys_length_desc(self):
        """校验 sorted_keys 按长度降序"""
        cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
        cb.load()
        keys = cb.get_sorted_keys()
        for i in range(len(keys) - 1):
            assert len(keys[i]) >= len(keys[i + 1])

    def test_missing_separator(self):
        """缺少分隔符"""
        cb = Codebook(os.path.join(DATA_DIR, "codebook_empty.txt"))
        cb.load()
        assert cb.exact_rule_count == 2


class TestCodebookValidate:
    """测试密码本校验"""

    def test_validate_valid(self):
        """正常密码本校验通过"""
        cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
        cb.load()
        messages = cb.validate()
        errors = [m for m in messages if m.startswith("ERROR")]
        assert len(errors) == 0

    def test_duplicate_replacement(self):
        """重复脱敏词检测"""
        cb = Codebook(os.path.join(DATA_DIR, "codebook_duplicate.txt"))
        cb.load()
        messages = cb.validate()
        errors = [m for m in messages if m.startswith("ERROR")]
        assert len(errors) > 0
        assert any("脱敏词重复" in e for e in errors)

    def test_cross_conflict(self):
        """交叉冲突检测"""
        cb = Codebook(os.path.join(DATA_DIR, "codebook_conflict.txt"))
        cb.load()
        messages = cb.validate()
        errors = [m for m in messages if m.startswith("ERROR")]
        assert len(errors) > 0
        assert any("交叉冲突" in e for e in errors)

    def test_bad_regex(self):
        """无效正则检测"""
        cb = Codebook(os.path.join(DATA_DIR, "codebook_bad_regex.txt"))
        with pytest.raises(CodebookError, match="正则表达式无效"):
            cb.load()

    def test_same_original_replacement_warning(self):
        """原文==脱敏词 WARNING"""
        # 创建临时密码本
        tmp_path = os.path.join(DATA_DIR, "_tmp_same.txt")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("Test==>Test\n")
        try:
            cb = Codebook(tmp_path)
            cb.load()
            messages = cb.validate()
            warnings = [m for m in messages if "WARNING" in m]
            assert any("无意义" in w for w in warnings)
        finally:
            os.remove(tmp_path)

    def test_duplicate_definition_is_rejected(self):
        """重复原文会造成静默覆盖，必须拒绝加载"""
        tmp_path = os.path.join(DATA_DIR, "_tmp_dup_def.txt")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("Key==>Value1\nKey==>Value2\n")
        try:
            cb = Codebook(tmp_path)
            with pytest.raises(CodebookError, match="重复定义原文"):
                cb.load()
        finally:
            os.remove(tmp_path)


class TestRegexModuleRequired:
    """A-03: 无 regex 模块时正则规则应拒绝加载（fail closed）。"""

    def test_regex_rule_rejected_without_regex_module(self, tmp_path):
        """无 regex 模块时，含正则规则的密码本应拒绝加载。"""
        cb_path = tmp_path / "cb_regex.txt"
        cb_path.write_text("regex:\\d{11}==>[手机号]\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        with patch("docmask.core.codebook._HAS_REGEX_MODULE", False):
            with pytest.raises(CodebookError, match="未安装 regex 模块"):
                cb.load()

    def test_exact_rules_work_without_regex_module(self, tmp_path):
        """无 regex 模块时，纯精确规则密码本仍可正常加载。"""
        cb_path = tmp_path / "cb_exact.txt"
        cb_path.write_text("张三==>李四\n秘密==>已脱敏\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        with patch("docmask.core.codebook._HAS_REGEX_MODULE", False):
            cb.load()
        assert cb.exact_rule_count == 2
        assert cb.regex_rule_count == 0
