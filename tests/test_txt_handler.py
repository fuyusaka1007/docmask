"""TXT 文件处理器测试"""
import os
import tempfile
import pytest
from docmask.core.codebook import Codebook
from docmask.core.masker import Masker
from docmask.core.restorer import Restorer
from docmask.handlers.txt_handler import TxtHandler

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


class TestTxtHandler:
    """测试 TXT 文件处理器"""

    def test_read(self):
        """读取文件"""
        handler = TxtHandler()
        content = handler.read(os.path.join(DATA_DIR, "sample.txt"))
        assert "张三" in content

    def test_mask(self, masker):
        """脱敏文件"""
        handler = TxtHandler()
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("张三和李明")
            tmp_in = f.name

        try:
            output_path, count, coverage = handler.mask(tmp_in, masker)
            assert os.path.exists(output_path)
            assert count == 2
            with open(output_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "李四" in content
            assert "王五" in content
        finally:
            os.remove(tmp_in)
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_restore(self, masker, restorer):
        """恢复文件"""
        handler = TxtHandler()
        original = "张三和李明"
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(original)
            tmp_in = f.name

        try:
            # 先脱敏
            masked_path, _, _ = handler.mask(tmp_in, masker)
            # 再恢复
            restored_path, count = handler.restore(masked_path, restorer)
            with open(restored_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content == original
        finally:
            for p in [tmp_in, masked_path, restored_path]:
                if os.path.exists(p):
                    os.remove(p)

    def test_output_file_exists_auto_increment(self, masker):
        """输出文件已存在时自动追加序号"""
        handler = TxtHandler()
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("张三")
            tmp_in = f.name

        try:
            # 第一次脱敏
            out1, _, _ = handler.mask(tmp_in, masker)
            # 手动创建同名文件
            with open(out1, "w", encoding="utf-8") as f:
                f.write("dummy")
            # 第二次脱敏，应自动追加序号
            out2, _, _ = handler.mask(tmp_in, masker)
            assert out1 != out2
            assert "_desensitized_1" in out2
        finally:
            os.remove(tmp_in)
            for p in [out1, out2]:
                if os.path.exists(p):
                    os.remove(p)