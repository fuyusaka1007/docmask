"""脱敏引擎测试"""
import os
import pytest
from docmask.core.codebook import Codebook
from docmask.core.masker import Masker

DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")


@pytest.fixture
def masker():
    """创建测试用 Masker"""
    cb = Codebook(os.path.join(DATA_DIR, "sample_codebook.txt"))
    cb.load()
    return Masker(cb)


class TestMasker:
    """测试脱敏引擎"""

    def test_exact_match(self, masker):
        """精确匹配"""
        result, count, hits = masker.mask_text("张三")
        assert result == "李四"
        assert count == 1
        assert hits.get("张三", 0) == 1

    def test_longest_match_priority(self, masker):
        """最长匹配优先：张三丰 > 张三"""
        result, count, hits = masker.mask_text("张三丰找张三")
        assert result == "赵六找李四", f"Expected '赵六找李四', got '{result}'"
        assert count == 2

    def test_no_match(self, masker):
        """无匹配时原样返回"""
        result, count, hits = masker.mask_text("没有敏感词")
        assert result == "没有敏感词"
        assert count == 0

    def test_regex_phone(self, masker):
        """正则匹配手机号"""
        result, count, hits = masker.mask_text("电话13912345678联系")
        assert "[手机号已脱敏]" in result
        assert count >= 1

    def test_regex_id_card(self, masker):
        """正则匹配身份证号"""
        result, count, hits = masker.mask_text("身份证32010219850315001X")
        assert "[身份证号已脱敏]" in result
        assert count >= 1

    def test_regex_email(self, masker):
        """正则匹配邮箱"""
        result, count, hits = masker.mask_text("邮箱test@example.com")
        assert "[邮箱已脱敏]" in result
        assert count >= 1

    def test_combined_rules(self, masker):
        """混合规则：精确+正则"""
        text = "张三 电话13800138000 邮箱zhangsan@test.com"
        result, count, hits = masker.mask_text(text)
        assert "李四" in result
        assert count >= 2

    def test_hit_counts(self, masker):
        """命中统计"""
        result, count, hits = masker.mask_text("张三 张三 张三丰")
        assert hits.get("张三", 0) == 2
        assert hits.get("张三丰", 0) == 1

    def test_coverage_report(self, masker):
        """覆盖率报告生成"""
        masker.mask_text("张三 李明")
        report = masker.generate_coverage_report()
        assert "张三" in report
        assert "命中" in report or "[命中]" in report

    def test_empty_text(self, masker):
        """空文本"""
        result, count, hits = masker.mask_text("")
        assert result == ""
        assert count == 0

    def test_one_pass_no_double_hit(self, masker):
        """一次遍历不二次命中"""
        # 密码本: A=>B, B=>C (交叉冲突，但这里测试无冲突情况)
        # 使用已有密码本测试：替换后不应再次匹配
        result, count, hits = masker.mask_text("张三")
        assert result == "李四"
        # 李四 不应再被匹配（密码本中无"李四"作为原文的规则）
        assert count == 1