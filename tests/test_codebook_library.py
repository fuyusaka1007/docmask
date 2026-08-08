"""CodebookLibrary 单元测试

覆盖：CRUD / 版本快照 / 恢复 / 导入导出 / 快照上限清理
"""
import os
import pytest

from docmask.core.codebook import Codebook, CodebookRule, CodebookError
from docmask.services.codebook_library import (
    CodebookLibrary,
    CodebookMeta,
    VersionInfo,
)


@pytest.fixture
def library(tmp_path):
    """使用临时目录的密码本库。"""
    return CodebookLibrary(base_dir=tmp_path / "codebooks")


@pytest.fixture
def sample_codebook(tmp_path):
    """创建一个含规则的密码本文件，返回路径。"""
    path = tmp_path / "sample.txt"
    path.write_text(
        "# 精确规则\n张三==>李四\n北京市==>⟦DM-ADDR-01⟧\n# 正则规则\nregex:\\d{11}==>PHONE\n",
        encoding="utf-8",
    )
    return str(path)


# ======================== CRUD ========================

class TestCreate:
    def test_create_returns_meta(self, library):
        meta = library.create("测试密码本", "描述")
        assert meta.id.startswith("cb-")
        assert meta.name == "测试密码本"
        assert meta.description == "描述"
        assert meta.version_count == 0
        assert meta.exact_rule_count == 0
        assert meta.regex_rule_count == 0

    def test_create_appears_in_list(self, library):
        library.create("密码本A")
        library.create("密码本B")
        books = library.list_codebooks()
        assert len(books) == 2
        names = {b.name for b in books}
        assert names == {"密码本A", "密码本B"}

    def test_create_empty_codebook(self, library):
        meta = library.create("空密码本")
        cb = library.load(meta.id)
        assert cb.exact_rule_count == 0
        assert cb.regex_rule_count == 0


class TestLoad:
    def test_load_after_save(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("导入")
        library.save(meta.id, cb)

        loaded = library.load(meta.id)
        assert loaded.exact_rule_count == 2
        assert loaded.regex_rule_count == 1
        assert loaded.forward_map.get("张三") == "李四"

    def test_load_nonexistent(self, library):
        with pytest.raises(CodebookError):
            library.load("nonexistent-id")


class TestSave:
    def test_save_generates_version(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        version = library.save(meta.id, cb)
        assert version.version_id.startswith("v-")
        assert version.exact_rule_count == 2
        assert version.regex_rule_count == 1
        assert "+2 精确规则" in version.change_summary

    def test_save_updates_index(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        library.save(meta.id, cb)

        books = library.list_codebooks()
        assert len(books) == 1
        assert books[0].exact_rule_count == 2
        assert books[0].regex_rule_count == 1
        assert books[0].version_count == 1

    def test_save_change_summary(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        v1 = library.save(meta.id, cb)
        assert "+2 精确规则" in v1.change_summary

        # 修改后保存
        cb2 = Codebook(sample_codebook)
        cb2.load()
        cb2.update_rules([
            CodebookRule(rule_type="exact", original="张三", replacement="李四"),
        ])
        v2 = library.save(meta.id, cb2)
        assert "-1 精确规则" in v2.change_summary
        assert "-1 正则规则" in v2.change_summary


class TestRename:
    def test_rename(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("原名")
        library.save(meta.id, cb)
        library.rename(meta.id, "新名")

        books = library.list_codebooks()
        assert books[0].name == "新名"


class TestDelete:
    def test_delete(self, library):
        meta = library.create("待删除")
        library.delete(meta.id)
        assert len(library.list_codebooks()) == 0

    def test_delete_removes_files(self, library):
        meta = library.create("待删除")
        assert os.path.exists(str(library._codebook_dir(meta.id)))
        library.delete(meta.id)
        assert not os.path.exists(str(library._codebook_dir(meta.id)))


class TestDuplicate:
    def test_duplicate_copies_rules(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("原始")
        library.save(meta.id, cb)

        new_meta = library.duplicate(meta.id, "副本")
        assert new_meta.name == "副本"
        assert new_meta.id != meta.id

        loaded = library.load(new_meta.id)
        assert loaded.exact_rule_count == 2
        assert loaded.regex_rule_count == 1


# ======================== 导入导出 ========================

class TestImportExport:
    def test_import_file(self, library, sample_codebook):
        meta = library.import_file(sample_codebook, "导入密码本")
        assert meta.name == "导入密码本"
        assert meta.exact_rule_count == 2
        assert meta.regex_rule_count == 1

    def test_export_file(self, library, sample_codebook, tmp_path):
        meta = library.import_file(sample_codebook, "源")
        dest = str(tmp_path / "exported.txt")
        library.export_file(meta.id, dest)

        assert os.path.exists(dest)
        cb = Codebook(dest)
        cb.load()
        assert cb.exact_rule_count == 2
        assert cb.regex_rule_count == 1

    def test_export_does_not_overwrite(self, library, sample_codebook, tmp_path):
        meta = library.import_file(sample_codebook, "源")
        dest = str(tmp_path / "exported.txt")
        with open(dest, "w", encoding="utf-8") as f:
            f.write("existing")

        with pytest.raises(FileExistsError):
            library.export_file(meta.id, dest)


# ======================== 版本管理 ========================

class TestVersions:
    def test_list_versions(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        library.save(meta.id, cb)

        versions = library.list_versions(meta.id)
        assert len(versions) == 1
        assert versions[0].exact_rule_count == 2

    def test_multiple_versions(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")

        # 第一次保存
        library.save(meta.id, cb)

        # 修改后第二次保存
        cb.update_rules([
            CodebookRule(rule_type="exact", original="张三", replacement="李四"),
            CodebookRule(rule_type="exact", original="王五", replacement="赵六"),
        ])
        library.save(meta.id, cb)

        versions = library.list_versions(meta.id)
        assert len(versions) == 2
        # 最近在前
        assert versions[0].exact_rule_count == 2
        assert versions[1].exact_rule_count == 2
        assert versions[0].regex_rule_count == 0
        assert versions[1].regex_rule_count == 1

    def test_load_version(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        v1 = library.save(meta.id, cb)

        # 修改后保存
        cb.update_rules([
            CodebookRule(rule_type="exact", original="只有一条", replacement="X"),
        ])
        library.save(meta.id, cb)

        # 加载第一个版本
        old_cb = library.load_version(meta.id, v1.version_id)
        assert old_cb.exact_rule_count == 2
        assert old_cb.regex_rule_count == 1

    def test_restore_version(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")
        v1 = library.save(meta.id, cb)

        # 修改后保存
        cb.update_rules([
            CodebookRule(rule_type="exact", original="只有一条", replacement="X"),
        ])
        library.save(meta.id, cb)

        # 恢复到第一个版本
        v3 = library.restore_version(meta.id, v1.version_id)
        assert v3.exact_rule_count == 2
        assert v3.regex_rule_count == 1

        # 确认 current.txt 已更新
        current_cb = library.load(meta.id)
        assert current_cb.exact_rule_count == 2
        assert current_cb.regex_rule_count == 1

    def test_max_versions_cleanup(self, library, sample_codebook):
        cb = Codebook(sample_codebook)
        cb.load()
        meta = library.create("测试")

        # 保存 MAX_VERSIONS + 5 次
        for i in range(CodebookLibrary.MAX_VERSIONS + 5):
            cb.update_rules([
                CodebookRule(
                    rule_type="exact",
                    original=f"规则{i}",
                    replacement=f"替换{i}",
                ),
            ])
            library.save(meta.id, cb)

        versions = library.list_versions(meta.id)
        assert len(versions) == CodebookLibrary.MAX_VERSIONS

        # 确认最旧的版本文件已被删除
        all_versions_meta = library._read_meta(meta.id)["versions"]
        for v in all_versions_meta:
            v_path = library._versions_dir(meta.id) / f"{v['version_id']}.txt"
            assert v_path.exists(), f"版本文件 {v['version_id']} 应存在"
