"""HistoryStore 单元测试

覆盖：append / query / count / clear / 上限滚动清理
"""
import pytest

from docmask.services.history_store import HistoryStore, HistoryEntry


@pytest.fixture
def store(tmp_path):
    """使用临时目录的历史存储。"""
    return HistoryStore(path=tmp_path / "history.jsonl")


def make_entry(timestamp: str, filename: str = "报告.docx", replacements: int = 10):
    return HistoryEntry(
        timestamp=timestamp,
        mode="mask",
        input_path=f"/test/{filename}",
        input_filename=filename,
        output_path=f"/test/{filename}_desensitized",
        codebook_name="默认密码本",
        codebook_version="v-20260808_150000",
        exact_rule_count=15,
        regex_rule_count=2,
        replacements=replacements,
        status="done",
    )


# ======================== append / count ========================

class TestAppend:
    def test_append_single(self, store):
        store.append(make_entry("2026-08-08T10:00:00"))
        assert store.count() == 1

    def test_append_multiple(self, store):
        for i in range(5):
            store.append(make_entry(f"2026-08-08T10:0{i}:00"))
        assert store.count() == 5

    def test_append_with_error(self, store):
        entry = make_entry("2026-08-08T10:00:00")
        entry.status = "failed"
        entry.error = "文件格式不支持"
        store.append(entry)
        entries = store.query(limit=1)
        assert entries[0].status == "failed"
        assert entries[0].error == "文件格式不支持"


# ======================== query ========================

class TestQuery:
    def test_query_returns_most_recent_first(self, store):
        store.append(make_entry("2026-08-08T10:00:00"))
        store.append(make_entry("2026-08-08T11:00:00"))
        store.append(make_entry("2026-08-08T12:00:00"))

        entries = store.query(limit=10)
        assert len(entries) == 3
        assert entries[0].timestamp == "2026-08-08T12:00:00"
        assert entries[1].timestamp == "2026-08-08T11:00:00"
        assert entries[2].timestamp == "2026-08-08T10:00:00"

    def test_query_limit(self, store):
        for i in range(10):
            store.append(make_entry(f"2026-08-08T10:{i:02d}:00"))

        entries = store.query(limit=3)
        assert len(entries) == 3

    def test_query_offset(self, store):
        for i in range(10):
            store.append(make_entry(f"2026-08-08T10:{i:02d}:00"))

        entries = store.query(limit=3, offset=2)
        assert len(entries) == 3
        # 跳过最近 2 条，返回第 3-5 条（倒序）
        assert entries[0].timestamp == "2026-08-08T10:07:00"

    def test_query_empty(self, store):
        entries = store.query()
        assert len(entries) == 0


# ======================== count ========================

class TestCount:
    def test_count_empty(self, store):
        assert store.count() == 0

    def test_count_after_appends(self, store):
        for i in range(10):
            store.append(make_entry(f"2026-08-08T10:{i:02d}:00"))
        assert store.count() == 10


# ======================== clear ========================

class TestClear:
    def test_clear_removes_all(self, store):
        for i in range(5):
            store.append(make_entry(f"2026-08-08T10:{i:02d}:00"))
        store.clear()
        assert store.count() == 0

    def test_clear_empty_store(self, store):
        store.clear()
        assert store.count() == 0

    def test_query_after_clear(self, store):
        store.append(make_entry("2026-08-08T10:00:00"))
        store.clear()
        entries = store.query()
        assert len(entries) == 0


# ======================== 上限清理 ========================

class TestMaxEntries:
    def test_trim_to_max(self, store):
        for i in range(HistoryStore.MAX_ENTRIES + 10):
            store.append(make_entry(f"2026-08-08T{i:04d}:00"))
        assert store.count() == HistoryStore.MAX_ENTRIES

    def test_trim_keeps_most_recent(self, store):
        for i in range(HistoryStore.MAX_ENTRIES + 5):
            store.append(make_entry(f"2026-08-08T{i:04d}:00"))

        entries = store.query(limit=1)
        # 最后追加的应该保留
        assert entries[0].timestamp == f"2026-08-08T{HistoryStore.MAX_ENTRIES + 4:04d}:00"

    def test_trim_drops_oldest(self, store):
        for i in range(HistoryStore.MAX_ENTRIES + 5):
            store.append(make_entry(f"2026-08-08T{i:04d}:00"))

        entries = store.query(limit=HistoryStore.MAX_ENTRIES)
        # 最旧的几条应该已被删除
        timestamps = [e.timestamp for e in entries]
        assert "2026-08-08T0000:00" not in timestamps
        assert "2026-08-08T0004:00" not in timestamps


# ======================== 数据完整性 ========================

class TestDataIntegrity:
    def test_all_fields_preserved(self, store):
        entry = HistoryEntry(
            timestamp="2026-08-08T15:30:00",
            mode="restore",
            input_path="/input/文件.docx",
            input_filename="文件.docx",
            output_path="/output/文件_restored.docx",
            codebook_name="测试本",
            codebook_version="v-20260808_100000",
            exact_rule_count=20,
            regex_rule_count=3,
            replacements=42,
            status="conflict",
            error="冲突信息",
        )
        store.append(entry)

        result = store.query(limit=1)[0]
        assert result.timestamp == "2026-08-08T15:30:00"
        assert result.mode == "restore"
        assert result.input_path == "/input/文件.docx"
        assert result.input_filename == "文件.docx"
        assert result.output_path == "/output/文件_restored.docx"
        assert result.codebook_name == "测试本"
        assert result.codebook_version == "v-20260808_100000"
        assert result.exact_rule_count == 20
        assert result.regex_rule_count == 3
        assert result.replacements == 42
        assert result.status == "conflict"
        assert result.error == "冲突信息"

    def test_unicode_preserved(self, store):
        entry = make_entry("2026-08-08T10:00:00", filename="中文文件名.docx")
        store.append(entry)
        result = store.query(limit=1)[0]
        assert result.input_filename == "中文文件名.docx"

    def test_none_error_serialized(self, store):
        entry = make_entry("2026-08-08T10:00:00")
        store.append(entry)
        result = store.query(limit=1)[0]
        assert result.error is None
