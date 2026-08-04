"""恢复引擎测试"""
import os
import pytest
from docmask.core.codebook import Codebook
from docmask.core.masker import Masker
from docmask.core.restorer import Restorer

DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")


@pytest.fixture
def codebook():
    cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
    cb.load()
    return cb


@pytest.fixture
def masker(codebook):
    return Masker(codebook)


@pytest.fixture
def restorer(codebook):
    return Restorer(codebook)


class TestRestorer:
    """测试恢复引擎"""

    def test_restore_exact(self, restorer):
        """恢复精确匹配"""
        result, count = restorer.restore_text("李四")
        assert result == "张三"
        assert count == 1

    def test_restore_no_match(self, restorer):
        """无匹配时原样返回"""
        result, count = restorer.restore_text("没有脱敏词")
        assert result == "没有脱敏词"
        assert count == 0

    def test_restore_roundtrip_exact(self, masker, restorer):
        """精确规则脱敏后恢复：roundtrip 一致"""
        original = "张三和张三丰都是某某科技有限公司的员工，联系李明"
        masked, _, _ = masker.mask_text(original)
        restored, count = restorer.restore_text(masked)
        # 精确规则应全部恢复
        assert restored == original, f"Expected '{original}', got '{restored}'"

    def test_regex_irreversible(self, masker, restorer):
        """正则规则不可逆"""
        original = "电话13912345678"
        masked, _, _ = masker.mask_text(original)
        restored, count = restorer.restore_text(masked)
        # 正则替换的不可恢复
        assert "13912345678" not in restored

    def test_restore_empty_text(self, restorer):
        """空文本恢复"""
        result, count = restorer.restore_text("")
        assert result == ""
        assert count == 0