"""CodebookRule / Codebook 编辑能力单元测试

覆盖：to_rules / update_rules / render / save / 往返一致性
"""
import os
import pytest

from docmask.core.codebook import Codebook, CodebookRule, CodebookError


# ======================== CodebookRule ========================

class TestCodebookRule:
    def test_exact_rule(self):
        rule = CodebookRule(rule_type="exact", original="张三", replacement="李四")
        assert rule.rule_type == "exact"
        assert rule.original == "张三"
        assert rule.replacement == "李四"
        assert rule.comment == ""

    def test_regex_rule_display_original(self):
        rule = CodebookRule(
            rule_type="regex",
            original="regex:\\d{11}",
            replacement="PHONE",
        )
        assert rule.display_original == "\\d{11}"

    def test_exact_rule_display_original(self):
        rule = CodebookRule(rule_type="exact", original="张三", replacement="李四")
        assert rule.display_original == "张三"

    def test_comment_field(self):
        rule = CodebookRule(
            rule_type="exact", original="张三", replacement="李四",
            comment="测试注释",
        )
        assert rule.comment == "测试注释"


# ======================== to_rules ========================

class TestToRules:
    def test_exact_rules(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n北京市==>⟦DM-ADDR-01⟧\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert len(rules) == 2
        assert rules[0].rule_type == "exact"
        assert rules[0].original == "张三"
        assert rules[0].replacement == "李四"
        assert rules[1].original == "北京市"
        assert rules[1].replacement == "⟦DM-ADDR-01⟧"

    def test_regex_rules(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("regex:\\d{11}==>PHONE\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert len(rules) == 1
        assert rules[0].rule_type == "regex"
        assert rules[0].original == "regex:\\d{11}"
        assert rules[0].replacement == "PHONE"

    def test_preserves_comments(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text(
            "# 精确规则\n张三==>李四\n# 正则规则\nregex:\\d{11}==>PHONE\n",
            encoding="utf-8",
        )
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert len(rules) == 2
        assert rules[0].comment == "精确规则"
        assert rules[1].comment == "正则规则"

    def test_consecutive_comments_merged(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text(
            "# 第一行注释\n# 第二行注释\n张三==>李四\n",
            encoding="utf-8",
        )
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert len(rules) == 1
        assert "第一行注释" in rules[0].comment
        assert "第二行注释" in rules[0].comment

    def test_empty_codebook(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("# 只有注释\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert len(rules) == 0

    def test_preserves_order(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text(
            "AAA==>001\nBBB==>002\nCCC==>003\n",
            encoding="utf-8",
        )
        cb = Codebook(str(path))
        cb.load()
        rules = cb.to_rules()
        assert [r.original for r in rules] == ["AAA", "BBB", "CCC"]


# ======================== render ========================

class TestRender:
    def test_render_basic(self, tmp_path):
        path = tmp_path / "cb.txt"
        content = "张三==>李四\nregex:\\d{11}==>PHONE\n"
        path.write_text(content, encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        rendered = cb.render()
        assert "张三==>李四" in rendered
        assert "regex:\\d{11}==>PHONE" in rendered

    def test_render_empty(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("# 只有注释\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        assert cb.render() == ""

    def test_round_trip_consistency(self, tmp_path):
        """render -> load -> render 应完全一致。"""
        path = tmp_path / "cb.txt"
        original_content = (
            "# 精确规则\n"
            "张三==>李四\n"
            "北京市==>⟦DM-ADDR-01⟧\n"
            "# 正则规则\n"
            "regex:\\d{11}==>PHONE\n"
        )
        path.write_text(original_content, encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        first_render = cb.render()

        # 写入第二次
        path2 = tmp_path / "cb2.txt"
        path2.write_text(first_render, encoding="utf-8")
        cb2 = Codebook(str(path2))
        cb2.load()
        second_render = cb2.render()

        assert first_render == second_render

    def test_render_with_comments(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("# 注释\n张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()
        rendered = cb.render()
        assert "# 注释" in rendered
        assert "张三==>李四" in rendered


# ======================== update_rules ========================

class TestUpdateRules:
    def test_update_basic(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="王五", replacement="赵六"),
            CodebookRule(rule_type="regex", original="regex:\\d{11}", replacement="PHONE"),
        ]
        messages = cb.update_rules(new_rules)
        assert cb.exact_rule_count == 1
        assert cb.regex_rule_count == 1
        assert cb.forward_map.get("王五") == "赵六"

    def test_update_validates_duplicates(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="张三", replacement="A"),
            CodebookRule(rule_type="exact", original="张三", replacement="B"),
        ]
        messages = cb.update_rules(new_rules)
        assert any("重复" in m for m in messages)

    def test_update_validates_replacement_conflict(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="A", replacement="X"),
            CodebookRule(rule_type="exact", original="B", replacement="X"),
        ]
        messages = cb.update_rules(new_rules)
        assert any("重复" in m and "脱敏词" in m for m in messages)

    def test_update_validates_cross_conflict(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="A", replacement="B"),
            CodebookRule(rule_type="exact", original="B", replacement="C"),
        ]
        messages = cb.update_rules(new_rules)
        assert any("交叉冲突" in m for m in messages)

    def test_update_empty_rules(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        messages = cb.update_rules([])
        assert cb.exact_rule_count == 0
        assert any("为空" in m for m in messages)

    def test_update_preserves_comments(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(
                rule_type="exact", original="王五", replacement="赵六",
                comment="新规则注释",
            ),
        ]
        cb.update_rules(new_rules)
        rules = cb.to_rules()
        assert len(rules) == 1
        assert rules[0].comment == "新规则注释"

    def test_update_regex_empty_match_rejected(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="regex", original="regex:a*", replacement="X"),
        ]
        messages = cb.update_rules(new_rules)
        assert any("空字符串" in m for m in messages)

    def test_update_incomplete_rule_returns_error(self, tmp_path):
        """A-07: 未填完整的规则行（原文为空）应返回 ERROR，而非被静默丢弃。"""
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="王五", replacement="赵六"),
            CodebookRule(rule_type="exact", original="", replacement="未填原文"),
        ]
        messages = cb.update_rules(new_rules)
        assert any(m.startswith("ERROR") for m in messages)

    def test_update_missing_replacement_returns_error(self, tmp_path):
        """A-07: 未填脱敏词的规则行应返回 ERROR。"""
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        new_rules = [
            CodebookRule(rule_type="exact", original="王五", replacement=""),
        ]
        messages = cb.update_rules(new_rules)
        assert any(m.startswith("ERROR") for m in messages)


# ======================== save ========================

class TestSave:
    def test_save_to_new_file(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        dest = str(tmp_path / "output.txt")
        cb.save(dest)
        assert os.path.exists(dest)

        # 验证内容可被重新加载
        cb2 = Codebook(dest)
        cb2.load()
        assert cb2.exact_rule_count == 1
        assert cb2.forward_map.get("张三") == "李四"

    def test_save_does_not_overwrite(self, tmp_path):
        path = tmp_path / "cb.txt"
        path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(path))
        cb.load()

        dest = str(tmp_path / "output.txt")
        with open(dest, "w", encoding="utf-8") as f:
            f.write("existing content")

        with pytest.raises(FileExistsError):
            cb.save(dest)

    def test_save_round_trip(self, tmp_path):
        """save -> load -> render 应与原始 render 一致。"""
        path = tmp_path / "cb.txt"
        path.write_text(
            "# 注释\n张三==>李四\nregex:\\d{11}==>PHONE\n",
            encoding="utf-8",
        )
        cb = Codebook(str(path))
        cb.load()
        original_render = cb.render()

        dest = str(tmp_path / "output.txt")
        cb.save(dest)

        cb2 = Codebook(dest)
        cb2.load()
        assert cb2.render() == original_render
