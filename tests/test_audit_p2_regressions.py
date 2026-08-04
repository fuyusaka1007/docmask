"""P2-1～P2-5 审计项回归测试。"""
import inspect
import os
import sys
from pathlib import Path

import pytest

from docmask.core.codebook import Codebook
from docmask.core.masker import Masker
from docmask.handlers.txt_handler import TxtHandler
from docmask.ui.controller import TaskController
from docmask.ui.state import AppState
from docmask.utils.file_utils import staged_output_path


# ======================== P2-1: Aho-Corasick 依赖和宣传已删除 ========================

def test_masker_has_no_automaton_attribute():
    """Masker 不应再保留 Aho-Corasick 自动机相关属性。"""
    src = inspect.getsource(Masker)
    assert "_automaton" not in src
    assert "_build_automaton" not in src
    assert "_mask_with_automaton" not in src
    assert "ahocorasick" not in src


def test_config_has_no_ac_threshold():
    """config 模块不应再导出 AC_AUTOMATON_THRESHOLD。"""
    from docmask import config
    assert not hasattr(config, "AC_AUTOMATON_THRESHOLD")


def test_requirements_no_pyahocorasick():
    """requirements.txt 不应再声明 pyahocorasick。"""
    req_path = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    with open(req_path, encoding="utf-8") as f:
        content = f.read()
    assert "pyahocorasick" not in content.lower()


# ======================== P2-3: add_files 同一调用内重复路径去重 ========================

def test_add_files_deduplicates_within_same_call(tmp_path):
    """同一调用中重复出现的路径只应添加一次。"""
    state = AppState()
    controller = TaskController(state, tk_root=None)
    f1 = tmp_path / "a.txt"
    f1.write_text("a", encoding="utf-8")
    path = str(f1)

    added = controller.add_files([path, path, path])
    assert len(added) == 1
    assert len(state.files) == 1


def test_add_files_deduplicates_across_calls(tmp_path):
    """跨调用添加同一路径只应保留一次。"""
    state = AppState()
    controller = TaskController(state, tk_root=None)
    f1 = tmp_path / "a.txt"
    f1.write_text("a", encoding="utf-8")
    path = str(f1)

    controller.add_files([path])
    controller.add_files([path])
    assert len(state.files) == 1


def test_add_files_deduplicates_symlink(tmp_path):
    """指向同一文件的符号链接应被去重。"""
    if sys.platform == "win32":
        pytest.skip("符号链接测试在 Windows 上需要额外权限")

    state = AppState()
    controller = TaskController(state, tk_root=None)
    original = tmp_path / "original.txt"
    original.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        os.symlink(original, link)
    except OSError:
        pytest.skip("无法创建符号链接")

    added = controller.add_files([str(original), str(link)])
    assert len(added) == 1
    assert len(state.files) == 1


# ======================== P2-4: TXT 输出统一为 UTF-8 ========================

def _make_codebook(tmp_path, rules: str) -> Masker:
    path = tmp_path / "codebook.txt"
    path.write_text(rules, encoding="utf-8")
    cb = Codebook(str(path))
    cb.load()
    return Masker(cb)


def test_txt_output_is_utf8_without_bom(tmp_path):
    """无论输入编码如何，输出始终为 UTF-8（无 BOM）。"""
    source = tmp_path / "input.txt"
    source.write_text("张三\n", encoding="utf-8-sig")  # 带 BOM
    masker = _make_codebook(tmp_path, "张三==>李四\n")

    output_path, _, _ = TxtHandler().mask(str(source), masker)

    with open(output_path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf")  # 无 BOM
    assert "李四".encode("utf-8") in raw


def test_txt_output_converts_gbk_to_utf8(tmp_path):
    """GBK 编码的输入应输出为 UTF-8。

    使用足够长的中文文本确保 chardet 能正确识别编码。
    """
    source = tmp_path / "input.txt"
    source.write_text("张三去北京天安门看升旗仪式\n", encoding="gbk")
    masker = _make_codebook(tmp_path, "张三==>李四\n")

    output_path, _, _ = TxtHandler().mask(str(source), masker)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "李四去北京天安门看升旗仪式\n"


def test_txt_output_normalizes_crlf_to_lf(tmp_path):
    """CRLF 换行应归一化为 LF。"""
    source = tmp_path / "input.txt"
    source.write_bytes("张三\r\n李明\r\n".encode("utf-8"))
    masker = _make_codebook(tmp_path, "张三==>A\n李明==>B\n")

    output_path, _, _ = TxtHandler().mask(str(source), masker)

    with open(output_path, "rb") as f:
        raw = f.read()
    assert b"\r\n" not in raw
    assert b"\n" in raw


def test_txt_output_normalizes_cr_to_lf(tmp_path):
    """CR 换行应归一化为 LF。"""
    source = tmp_path / "input.txt"
    source.write_bytes("张三\r李明".encode("utf-8"))
    masker = _make_codebook(tmp_path, "张三==>A\n李明==>B\n")

    output_path, _, _ = TxtHandler().mask(str(source), masker)

    with open(output_path, "rb") as f:
        raw = f.read()
    assert b"\r" not in raw


def test_txt_round_trip_preserves_content(tmp_path):
    """脱敏→恢复往返应保持内容一致（LF 归一化后）。"""
    original = "张三和李明\n第二行"
    source = tmp_path / "input.txt"
    source.write_text(original, encoding="utf-8")
    masker = _make_codebook(tmp_path, "张三==>A\n李明==>B\n")

    handler = TxtHandler()
    from docmask.core.restorer import Restorer
    cb = Codebook(str(tmp_path / "codebook.txt"))
    cb.load()
    restorer = Restorer(cb)

    masked_path, _, _ = handler.mask(str(source), masker)
    restored_path, _ = handler.restore(masked_path, restorer)

    assert Path(restored_path).read_text(encoding="utf-8") == original


# ======================== P2-5: 原子写入 ========================

def test_staged_output_cleans_up_temp_on_failure(tmp_path):
    """处理器抛异常时不应残留临时文件，也不应创建最终文件。"""
    final = tmp_path / "output.txt"
    with pytest.raises(RuntimeError):
        with staged_output_path(str(final)) as temp_path:
            raise RuntimeError("模拟处理失败")
    assert not final.exists()
    temp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert not temp_files


def test_staged_output_creates_final_on_success(tmp_path):
    """成功时最终文件应存在。"""
    final = tmp_path / "output.txt"
    with staged_output_path(str(final)) as temp_path:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("content")
    assert final.exists()
    assert final.read_text(encoding="utf-8") == "content"


def test_staged_output_refuses_overwrite(tmp_path):
    """目标已存在时应拒绝覆盖。"""
    final = tmp_path / "output.txt"
    final.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        with staged_output_path(str(final)) as temp_path:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write("new")
    assert final.read_text(encoding="utf-8") == "keep"


def test_txt_handler_failure_leaves_no_partial_output(tmp_path):
    """TxtHandler 脱敏失败时不应留下不完整的输出文件。"""
    source = tmp_path / "input.txt"
    output = tmp_path / "output.txt"

    # 使用会触发冲突的密码本让 mask 失败
    cb_path = tmp_path / "codebook.txt"
    cb_path.write_text("张三==>李四\n", encoding="utf-8")
    cb = Codebook(str(cb_path))
    cb.load()
    masker = Masker(cb)

    # 在源文件中放入脱敏词制造冲突
    source.write_text("张三李四", encoding="utf-8")

    with pytest.raises(Exception):
        TxtHandler().mask(str(source), masker, output_path=str(output))
    assert not output.exists()
