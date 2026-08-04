"""文件收集与 Handler 选择公共服务测试"""
import os
import tempfile
import pytest
from pathlib import Path

from docmask.services.file_service import collect_files, get_handler
from docmask.handlers.txt_handler import TxtHandler
from docmask.handlers.docx_handler import DocxHandler
from docmask.handlers.doc_handler import DocHandler


class TestCollectFiles:
    """测试 collect_files()"""

    def test_single_file_matching_format(self):
        """单个文件且格式匹配"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp = f.name
        try:
            result = collect_files(tmp, ["txt"])
            assert result == [tmp]
        finally:
            os.remove(tmp)

    def test_single_file_not_matching_format(self):
        """单个文件但格式不匹配"""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp = f.name
        try:
            result = collect_files(tmp, ["txt", "docx"])
            assert result == []
        finally:
            os.remove(tmp)

    def test_single_file_default_formats(self):
        """单个文件使用默认格式"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            tmp = f.name
        try:
            result = collect_files(tmp)
            assert result == [tmp]
        finally:
            os.remove(tmp)

    def test_directory_recursive(self):
        """目录递归扫描"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建多级目录
            sub = Path(tmpdir) / "subdir"
            sub.mkdir()
            # 创建不同格式文件
            (Path(tmpdir) / "a.txt").touch()
            (Path(tmpdir) / "b.docx").touch()
            (sub / "c.txt").touch()
            (sub / "d.pdf").touch()

            result = collect_files(tmpdir, ["txt", "docx"], recursive=True)
            # 应找到 a.txt, b.docx, subdir/c.txt
            names = sorted(Path(p).name for p in result)
            assert names == ["a.txt", "b.docx", "c.txt"]

    def test_directory_non_recursive(self):
        """目录非递归扫描"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "subdir"
            sub.mkdir()
            (Path(tmpdir) / "a.txt").touch()
            (sub / "c.txt").touch()

            result = collect_files(tmpdir, ["txt"], recursive=False)
            names = [Path(p).name for p in result]
            assert names == ["a.txt"]

    def test_directory_empty(self):
        """空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = collect_files(tmpdir, ["txt"])
            assert result == []

    def test_format_normalization(self):
        """格式参数归一化：带点号和大写"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp = f.name
        try:
            # 带点号、大写都应正常匹配
            result = collect_files(tmp, [".TXT", "TXT"])
            assert result == [tmp]
        finally:
            os.remove(tmp)

    def test_nonexistent_path(self):
        """不存在的路径返回空列表"""
        result = collect_files("/nonexistent/path/file.txt", ["txt"])
        assert result == []

    def test_results_sorted(self):
        """结果应排序"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "c.txt").touch()
            (Path(tmpdir) / "a.txt").touch()
            (Path(tmpdir) / "b.txt").touch()

            result = collect_files(tmpdir, ["txt"])
            names = [Path(p).name for p in result]
            assert names == ["a.txt", "b.txt", "c.txt"]


class TestGetHandler:
    """测试 get_handler()"""

    def test_txt_handler(self):
        handler, fmt = get_handler("test.txt")
        assert isinstance(handler, TxtHandler)
        assert fmt == "txt"

    def test_docx_handler(self):
        handler, fmt = get_handler("test.docx")
        assert isinstance(handler, DocxHandler)
        assert fmt == "docx"

    def test_doc_handler(self):
        handler, fmt = get_handler("test.doc")
        assert isinstance(handler, DocHandler)
        assert fmt == "doc"

    def test_unsupported_format(self):
        handler, fmt = get_handler("test.pdf")
        assert handler is None
        assert fmt == ".pdf"

    def test_case_insensitive(self):
        """扩展名大小写不敏感"""
        handler, fmt = get_handler("test.TXT")
        assert isinstance(handler, TxtHandler)
        assert fmt == "txt"

    def test_no_extension(self):
        """无扩展名"""
        handler, fmt = get_handler("README")
        assert handler is None
        assert fmt == ""
