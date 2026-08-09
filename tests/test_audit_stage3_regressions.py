"""Stage 3 审计修复回归测试。

覆盖：A-13 跨节点扫描修复 / A-14 拖放解析修复 / A-15 格式过滤器 /
      A-16 CLI 空输入退出码 / A-18 停止/冲突展示 / A-19 索引校验 /
      A-20 回调隔离修复
"""
from __future__ import annotations

import json
import os
import queue
import tempfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from lxml import etree

from docmask.core.codebook import Codebook, CodebookError
from docmask.core.masker import Masker
from docmask.handlers.docx_handler import DocxHandler
from docmask.services.codebook_library import CodebookLibrary
from docmask.services.history_store import HistoryStore, HistoryEntry
from docmask.ui.controller import TaskController
from docmask.ui.state import AppState, FileStatus, Mode, create_file_item
from docmask.ui.widgets.file_queue import _parse_dnd_files


# ======================== A-13: 跨节点拆分扫描修复 ========================


def _make_codebook(tmp_path: Path, rules: str) -> Codebook:
    path = tmp_path / "codebook.txt"
    path.write_text(rules, encoding="utf-8")
    cb = Codebook(str(path))
    cb.load()
    return cb


def _make_unsupported_doc(text_nodes: list[str]):
    """创建包含不支持部件的 mock doc，文本节点按给定列表拆分。"""
    inner = "".join(f"<a:t>{t}</a:t>" for t in text_nodes)
    chart_xml = (
        f'<c:chart xmlns:c="urn:chart" xmlns:a="urn:drawing">{inner}</c:chart>'
    ).encode("utf-8")
    part = SimpleNamespace(
        partname="/word/charts/chart1.xml", blob=chart_xml, rels={}
    )
    return SimpleNamespace(
        part=SimpleNamespace(package=SimpleNamespace(parts=[part]))
    )


class TestCrossNodeScanA13:
    """A-13: 三/四节点拆分扫描应实际生效。"""

    def test_3_node_split_detected(self, tmp_path):
        """3 节点拆分 (S + EC + RET) 应被检测到。"""
        cb = _make_codebook(tmp_path, "SECRET==>MASKED\n")
        doc = _make_unsupported_doc(["S", "EC", "RET"])
        warnings = DocxHandler()._scan_unsupported_parts(
            doc, Masker(cb), original_texts=set()
        )
        assert len(warnings) == 1
        assert "跨节点" in warnings[0]

    def test_4_node_split_detected(self, tmp_path):
        """4 节点拆分 (S + E + C + RET) 应被检测到。"""
        cb = _make_codebook(tmp_path, "SECRET==>MASKED\n")
        doc = _make_unsupported_doc(["S", "E", "C", "RET"])
        warnings = DocxHandler()._scan_unsupported_parts(
            doc, Masker(cb), original_texts=set()
        )
        assert len(warnings) == 1
        assert "跨节点" in warnings[0]

    def test_2_node_split_still_works(self, tmp_path):
        """2 节点拆分 (SEC + RET) 仍应被检测到。"""
        cb = _make_codebook(tmp_path, "SECRET==>MASKED\n")
        doc = _make_unsupported_doc(["SEC", "RET"])
        warnings = DocxHandler()._scan_unsupported_parts(
            doc, Masker(cb), original_texts=set()
        )
        assert len(warnings) == 1

    def test_5_node_split_not_detected(self, tmp_path):
        """5 节点拆分超出窗口上限（4），不应检测到。"""
        cb = _make_codebook(tmp_path, "SECRET==>MASKED\n")
        doc = _make_unsupported_doc(["S", "E", "C", "R", "ET"])
        warnings = DocxHandler()._scan_unsupported_parts(
            doc, Masker(cb), original_texts=set()
        )
        assert len(warnings) == 0

    def test_no_false_positive_on_unrelated_nodes(self, tmp_path):
        """不相关的文本节点不应触发告警。"""
        cb = _make_codebook(tmp_path, "SECRET==>MASKED\n")
        doc = _make_unsupported_doc(["hello", "world", "foo"])
        warnings = DocxHandler()._scan_unsupported_parts(
            doc, Masker(cb), original_texts=set()
        )
        assert len(warnings) == 0


# ======================== A-14: 拖放解析修复 ========================


class TestDndParseA14:
    """A-14: _parse_dnd_files 支持 list/tuple 输入（splitlist 回退路径）。"""

    def test_list_input_passes_through(self):
        """splitlist 返回的列表应直接通过。"""
        result = _parse_dnd_files(["/a/b.txt", "/c/d.docx"])
        assert result == ["/a/b.txt", "/c/d.docx"]

    def test_tuple_input_passes_through(self):
        result = _parse_dnd_files(("/a/b.txt",))
        assert result == ["/a/b.txt"]

    def test_brace_format_still_works(self):
        """Windows 花括号格式仍应作为回退正常工作。"""
        data = r"{C:\Users\test\file.txt} {C:\Users\test\file2.docx}"
        result = _parse_dnd_files(data)
        assert len(result) == 2

    def test_newline_format_still_works(self):
        """macOS/Linux 换行分隔格式仍应作为回退正常工作。"""
        data = "/home/user/a.txt\n/home/user/b.docx\n"
        result = _parse_dnd_files(data)
        assert len(result) == 2

    def test_empty_strings_filtered(self):
        result = _parse_dnd_files(["", "/a/b.txt", ""])
        assert result == ["/a/b.txt"]


# ======================== A-15: 格式过滤器影响手动选择 ========================


class TestFormatFilterA15:
    """A-15: add_files 检查 format_filters，与目录扫描统一。"""

    def test_disabled_format_rejected(self, tmp_path):
        """关闭 DOC 格式后，手动选择 DOC 文件应被拒绝。"""
        txt_file = tmp_path / "a.txt"
        txt_file.write_text("content", encoding="utf-8")
        doc_file = tmp_path / "b.doc"
        doc_file.write_text("content", encoding="utf-8")

        state = AppState()
        state.format_filters = {"docx", "txt"}  # DOC 被禁用
        controller = TaskController(state, tk_root=None)

        added = controller.add_files([str(txt_file), str(doc_file)])
        assert len(added) == 1
        assert added[0].fmt == "txt"

    def test_all_formats_allowed(self, tmp_path):
        """所有格式启用时，全部文件应被接受。"""
        txt_file = tmp_path / "a.txt"
        txt_file.write_text("content", encoding="utf-8")
        docx_file = tmp_path / "b.docx"
        docx_file.write_text("content", encoding="utf-8")

        state = AppState()
        state.format_filters = {"docx", "doc", "txt"}
        controller = TaskController(state, tk_root=None)

        added = controller.add_files([str(txt_file), str(docx_file)])
        assert len(added) == 2

    def test_is_format_allowed_method(self):
        """_is_format_allowed 正确反映当前过滤器。"""
        state = AppState()
        state.format_filters = {"txt"}
        controller = TaskController(state, tk_root=None)

        assert controller._is_format_allowed("txt") is True
        assert controller._is_format_allowed("docx") is False
        assert controller._is_format_allowed("doc") is False


# ======================== A-16: CLI 空输入退出码 ========================


class TestCliEmptyInputA16:
    """A-16: CLI 空输入返回非零，--allow-empty 返回 0。"""

    def _make_codebook(self, tmp_path):
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        return str(cb_path)

    def test_mask_empty_dir_returns_2(self, tmp_path):
        import docmask.cli as cli_module

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = SimpleNamespace(
            input=str(empty_dir), codebook=self._make_codebook(tmp_path),
            output=None, format=None, report=False, allow_empty=False,
        )
        rc = cli_module.cmd_mask(args)
        assert rc == 2

    def test_mask_empty_dir_allow_empty_returns_0(self, tmp_path):
        import docmask.cli as cli_module

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = SimpleNamespace(
            input=str(empty_dir), codebook=self._make_codebook(tmp_path),
            output=None, format=None, report=False, allow_empty=True,
        )
        rc = cli_module.cmd_mask(args)
        assert rc == 0

    def test_restore_empty_dir_returns_2(self, tmp_path):
        import docmask.cli as cli_module

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = SimpleNamespace(
            input=str(empty_dir), codebook=self._make_codebook(tmp_path),
            output=None, format=None, allow_empty=False,
        )
        rc = cli_module.cmd_restore(args)
        assert rc == 2

    def test_restore_empty_dir_allow_empty_returns_0(self, tmp_path):
        import docmask.cli as cli_module

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = SimpleNamespace(
            input=str(empty_dir), codebook=self._make_codebook(tmp_path),
            output=None, format=None, allow_empty=True,
        )
        rc = cli_module.cmd_restore(args)
        assert rc == 0


# ======================== A-18: 停止/冲突信息展示 ========================


class TestHistoryConflictDetailsA18:
    """A-18: 历史记录中 conflict_details 写入 error 字段。"""

    def test_conflict_details_recorded_in_history(self, tmp_path):
        """冲突文件的 conflict_details 应写入历史记录的 error 字段。"""
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        codebook = Codebook(str(cb_path))
        codebook.load()

        state = AppState()
        state.codebook.codebook = codebook
        state.codebook.valid = True
        state.history_enabled = True

        input_file = tmp_path / "input.txt"
        input_file.write_text("张三", encoding="utf-8")

        item = create_file_item(str(input_file))
        item.status = FileStatus.CONFLICT
        item.conflict_details = "脱敏词冲突：李四"
        item.error_message = None
        state.files = [item]

        controller = TaskController(state, tk_root=None)
        # 手动设置 task_context 以便 record_history 能工作
        from docmask.ui.state import TaskContext
        controller._task_context = TaskContext(
            mode=Mode.MASK, codebook=codebook, codebook_name="test",
            codebook_version="v1", exact_count=1, regex_count=0,
            output_same_dir=True, output_dir=None, generate_report=False,
            history_enabled=True,
        )

        # 直接调用 record_history（同步，不通过 Tk after）
        controller.record_history([item])

        # 后台线程写入，等待完成
        import time
        time.sleep(0.2)

        entries = controller.query_history(limit=10)
        assert len(entries) == 1
        assert entries[0].status == "conflict"
        assert entries[0].error == "脱敏词冲突：李四"

    def test_stopped_status_recorded_in_history(self, tmp_path):
        """停止状态应正确记录在历史中。"""
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        codebook = Codebook(str(cb_path))
        codebook.load()

        state = AppState()
        state.codebook.codebook = codebook
        state.codebook.valid = True
        state.history_enabled = True

        input_file = tmp_path / "input.txt"
        input_file.write_text("张三", encoding="utf-8")

        item = create_file_item(str(input_file))
        item.status = FileStatus.STOPPED
        state.files = [item]

        controller = TaskController(state, tk_root=None)
        from docmask.ui.state import TaskContext
        controller._task_context = TaskContext(
            mode=Mode.MASK, codebook=codebook, codebook_name="test",
            codebook_version="v1", exact_count=1, regex_count=0,
            output_same_dir=True, output_dir=None, generate_report=False,
            history_enabled=True,
        )

        controller.record_history([item])

        import time
        time.sleep(0.2)

        entries = controller.query_history(limit=10)
        assert len(entries) == 1
        assert entries[0].status == "stopped"

    def test_error_message_takes_precedence_over_conflict(self, tmp_path):
        """error_message 和 conflict_details 都存在时，error_message 优先。"""
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        codebook = Codebook(str(cb_path))
        codebook.load()

        state = AppState()
        state.codebook.codebook = codebook
        state.codebook.valid = True
        state.history_enabled = True

        input_file = tmp_path / "input.txt"
        input_file.write_text("张三", encoding="utf-8")

        item = create_file_item(str(input_file))
        item.status = FileStatus.FAILED
        item.error_message = "文件处理失败"
        item.conflict_details = "冲突详情"
        state.files = [item]

        controller = TaskController(state, tk_root=None)
        from docmask.ui.state import TaskContext
        controller._task_context = TaskContext(
            mode=Mode.MASK, codebook=codebook, codebook_name="test",
            codebook_version="v1", exact_count=1, regex_count=0,
            output_same_dir=True, output_dir=None, generate_report=False,
            history_enabled=True,
        )

        controller.record_history([item])

        import time
        time.sleep(0.2)

        entries = controller.query_history(limit=10)
        assert len(entries) == 1
        assert entries[0].error == "文件处理失败"


# ======================== A-19: 密码本库索引校验与路径安全 ========================


class TestCodebookIdValidationA19:
    """A-19: ID 格式校验防止路径遍历。"""

    def test_invalid_codebook_id_rejected(self, tmp_path):
        lib = CodebookLibrary(base_dir=tmp_path / "library")
        with pytest.raises(CodebookError, match="无效的密码本 ID"):
            lib.load("invalid-id")

    def test_path_traversal_rejected(self, tmp_path):
        lib = CodebookLibrary(base_dir=tmp_path / "library")
        with pytest.raises(CodebookError, match="无效的密码本 ID"):
            lib.load("../../etc/passwd")

    def test_valid_codebook_id_accepted(self, tmp_path):
        """合法 ID 格式不抛异常（密码本不存在时抛 CodebookError 但不是 ID 校验错误）。"""
        lib = CodebookLibrary(base_dir=tmp_path / "library")
        with pytest.raises(CodebookError, match="密码本不存在"):
            lib.load("cb-deadbeef")

    def test_delete_with_invalid_id_rejected(self, tmp_path):
        """删除操作使用无效 ID 时应拒绝，不执行 rmtree。"""
        lib = CodebookLibrary(base_dir=tmp_path / "library")
        with pytest.raises(CodebookError, match="无效的密码本 ID"):
            lib.delete("../../etc")

    def test_invalid_version_id_rejected(self, tmp_path):
        lib = CodebookLibrary(base_dir=tmp_path / "library")
        meta = lib.create("test")
        with pytest.raises(CodebookError, match="无效的版本 ID"):
            lib.load_version(meta.id, "../../etc/passwd")


class TestIndexRebuildA19:
    """A-19: 索引损坏时从子目录重建。"""

    def test_corrupt_index_triggers_rebuild(self, tmp_path):
        """索引文件内容损坏时，应从子目录重建。"""
        base = tmp_path / "library"
        lib = CodebookLibrary(base_dir=base)

        # 创建一个密码本
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        cb.load()
        meta = lib.create("测试密码本")
        lib.save(meta.id, cb)

        # 损坏索引文件
        (base / "index.json").write_text("INVALID JSON{", encoding="utf-8")

        # 重新初始化应触发重建
        lib2 = CodebookLibrary(base_dir=base)
        codebooks = lib2.list_codebooks()
        assert len(codebooks) == 1
        assert codebooks[0].name == "测试密码本"

    def test_missing_index_triggers_rebuild(self, tmp_path):
        """索引文件不存在时，应从子目录重建。"""
        base = tmp_path / "library"
        lib = CodebookLibrary(base_dir=base)

        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        cb.load()
        meta = lib.create("测试")
        lib.save(meta.id, cb)

        # 删除索引文件
        (base / "index.json").unlink()

        lib2 = CodebookLibrary(base_dir=base)
        codebooks = lib2.list_codebooks()
        assert len(codebooks) == 1
        assert codebooks[0].id == meta.id

    def test_invalid_index_structure_triggers_rebuild(self, tmp_path):
        """索引结构无效（非 dict 或缺 codebooks 键）时重建。"""
        base = tmp_path / "library"
        lib = CodebookLibrary(base_dir=base)

        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        cb.load()
        meta = lib.create("测试")
        lib.save(meta.id, cb)

        # 写入结构无效的索引
        (base / "index.json").write_text('{"wrong_key": 123}', encoding="utf-8")

        lib2 = CodebookLibrary(base_dir=base)
        codebooks = lib2.list_codebooks()
        assert len(codebooks) == 1

    def test_rebuild_ignores_invalid_directories(self, tmp_path):
        """重建时忽略不符合 ID 格式的目录。"""
        base = tmp_path / "library"
        base.mkdir()
        # 创建一个无效目录名
        (base / "invalid-dir").mkdir()
        # 创建一个有效密码本
        lib = CodebookLibrary(base_dir=base)
        cb_path = tmp_path / "cb.txt"
        cb_path.write_text("张三==>李四\n", encoding="utf-8")
        cb = Codebook(str(cb_path))
        cb.load()
        meta = lib.create("测试")
        lib.save(meta.id, cb)

        # 损坏索引触发重建
        (base / "index.json").write_text("INVALID", encoding="utf-8")
        lib2 = CodebookLibrary(base_dir=base)
        codebooks = lib2.list_codebooks()
        assert len(codebooks) == 1
        assert codebooks[0].id == meta.id


# ======================== A-20: 回调异常隔离修复 ========================


class TestCallbackIsolationA20:
    """A-20: partial/callable 无 __name__ 时不中断事件队列。"""

    def test_partial_callback_exception_isolated(self):
        """functools.partial 对象无 __name__，异常不应中断队列。"""
        state = AppState()
        controller = TaskController(state, tk_root=None)

        call_log = []

        def failing_callback(msg):
            call_log.append(f"failing: {msg}")
            raise ValueError("intentional failure")

        def normal_callback(msg):
            call_log.append(f"normal: {msg}")

        failing_partial = partial(failing_callback, "test")

        controller._safe_after(failing_partial)
        controller._safe_after(normal_callback, "ok")

        processed = controller.process_pending_events()

        # 两个回调都应被处理（异常被隔离）
        assert processed == 2
        assert len(call_log) == 2
        assert "failing" in call_log[0]
        assert "normal" in call_log[1]

    def test_callable_object_exception_isolated(self):
        """无 __name__ 的 callable 对象异常也应被隔离。"""
        state = AppState()
        controller = TaskController(state, tk_root=None)

        class CallableObj:
            def __call__(self):
                raise RuntimeError("callable object failure")

        class NamedCallable:
            __name__ = "named"

            def __call__(self):
                pass

        controller._safe_after(CallableObj())
        controller._safe_after(NamedCallable())

        processed = controller.process_pending_events()
        assert processed == 2

    def test_lambda_callback_exception_isolated(self):
        """lambda 有 __name__ == '<lambda>'，异常应被隔离。"""
        state = AppState()
        controller = TaskController(state, tk_root=None)

        controller._safe_after(lambda: (_ for _ in ()).throw(ValueError("boom")))
        controller._safe_after(lambda: None)

        processed = controller.process_pending_events()
        assert processed == 2
