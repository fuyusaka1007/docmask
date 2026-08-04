"""P0-10～P0-12、P1-1～P1-6 审计项回归测试。"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml import OxmlElement

from docmask.core.codebook import Codebook, CodebookError
from docmask.core.masker import Masker
from docmask.core.restorer import Restorer
from docmask.handlers.docx_handler import DocxHandler
from docmask.handlers.txt_handler import TxtHandler
from docmask.services.file_service import scan_files
from docmask.ui.state import AppState, create_file_item
from docmask.ui.pages.results_page import ResultsPage
from docmask.utils.file_utils import resolve_output_path


def make_codebook(tmp_path: Path, rules: str) -> Codebook:
    path = tmp_path / "codebook.txt"
    path.write_text(rules, encoding="utf-8")
    codebook = Codebook(str(path))
    codebook.load()
    return codebook


def test_empty_matching_regex_is_rejected(tmp_path):
    path = tmp_path / "codebook.txt"
    path.write_text("regex:.*?==>X\n", encoding="utf-8")
    with pytest.raises(CodebookError, match="可匹配空字符串"):
        Codebook(str(path)).load()


def test_replacements_are_globally_unique_across_rule_types(tmp_path):
    codebook = make_codebook(tmp_path, "A==>MASK\nregex:\\d+==>MASK\n")
    assert any(message.startswith("ERROR") for message in codebook.validate())


def test_regex_replacement_is_literal_and_generated_text_is_not_reprocessed(tmp_path):
    codebook = make_codebook(
        tmp_path, "A==>123\nregex:\\d+==>\\1-LITERAL\n"
    )
    result, count, _hits = Masker(codebook).mask_text("A 456")
    assert result == "123 \\1-LITERAL"
    assert count == 2


def test_document_reversibility_is_separate_from_structure_validation(tmp_path):
    codebook = make_codebook(tmp_path, "A==>MASK\nregex:\\d+==>NUMBER\n")
    assert not [m for m in codebook.validate() if m.startswith("ERROR")]
    messages = codebook.validate_reversibility("A 123")
    assert any("正则规则" in message and "不能保证" in message for message in messages)


def test_cli_output_resolution_distinguishes_single_and_batch(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    explicit = tmp_path / "named.txt"
    explicit.write_text("keep", encoding="utf-8")

    single = resolve_output_path(
        str(source), str(explicit), suffix="_masked", batch_mode=False
    )
    assert Path(single).name == "named_1.txt"
    assert explicit.read_text(encoding="utf-8") == "keep"

    output_dir = tmp_path / "batch-output"
    batch = resolve_output_path(
        str(source), str(output_dir), suffix="_masked", batch_mode=True
    )
    assert Path(batch) == output_dir / "source_masked.txt"


def test_handler_refuses_to_overwrite_explicit_output(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("A", encoding="utf-8")
    output = tmp_path / "output.txt"
    output.write_text("keep", encoding="utf-8")
    codebook = make_codebook(tmp_path, "A==>B\n")

    with pytest.raises(FileExistsError):
        TxtHandler().mask(str(source), Masker(codebook), output_path=str(output))
    assert output.read_text(encoding="utf-8") == "keep"


def test_docx_nested_table_and_tracked_insertion_round_trip(tmp_path):
    source = tmp_path / "complex.docx"
    doc = Document()
    outer = doc.add_table(rows=1, cols=1)
    nested = outer.cell(0, 0).add_table(rows=1, cols=1)
    nested.cell(0, 0).paragraphs[0].add_run("SECRET")

    paragraph = doc.add_paragraph()
    insertion = OxmlElement("w:ins")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "SECRET"
    run.append(text)
    insertion.append(run)
    paragraph._p.append(insertion)
    doc.save(source)

    codebook = make_codebook(tmp_path, "SECRET==>MASKED\n")
    handler = DocxHandler()
    masked, masked_count, _ = handler.mask(str(source), Masker(codebook))
    restored, restored_count = handler.restore(masked, Restorer(codebook))

    masked_xml = Document(masked).element.xml
    restored_xml = Document(restored).element.xml
    assert masked_count == 2
    assert restored_count == 2
    assert "SECRET" not in masked_xml
    assert masked_xml.count("MASKED") == 2
    assert restored_xml.count("SECRET") == 2


def test_docx_declares_capability_boundaries():
    matrix = DocxHandler.OPC_CAPABILITY_MATRIX
    assert matrix["word/comments*.xml"] == "supported"
    assert matrix["word/charts/*"] == "warn-only"
    assert matrix["external hyperlink targets"] == "warn-only"


def test_docx_comment_text_and_author_round_trip(tmp_path):
    """批注文本和作者脱敏/恢复往返测试。

    注意：python-docx 1.1.0 无 Document.comments/add_comment API，
    但 DocxHandler 在 XML 层级处理 word/comments.xml，因此测试直接
    操作 OPC 包来创建和验证批注。
    """
    from lxml import etree
    from io import BytesIO
    import zipfile
    import re

    source = tmp_path / "comments.docx"
    doc = Document()
    doc.add_paragraph("anchor text")
    # 手动注入 word/comments.xml 到 OPC 包
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    comments_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:comment w:id="0" w:author="SECRET" w:initials="S">'
        b'<w:p><w:r><w:t>SECRET comment</w:t></w:r></w:p>'
        b'</w:comment></w:comments>'
    )

    with (
        zipfile.ZipFile(buf, "r") as zin,
        zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        # 复制所有现有条目
        for item in zin.infolist():
            if item.filename == "[Content_Types].xml":
                data = zin.read(item)
                # 注入 comments 的内容类型声明
                before = b'</Types>'
                override = b'<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                data = data.replace(before, override + before)
                zout.writestr(item, data)
            elif item.filename == "word/_rels/document.xml.rels":
                data = zin.read(item)
                before = b'</Relationships>'
                rel = (
                    b'<Relationship Id="rIdComments" '
                    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
                    b'Target="comments.xml"/>'
                )
                data = data.replace(before, rel + before)
                zout.writestr(item, data)
            else:
                zout.writestr(item, zin.read(item))
        # 写入 comments.xml
        zout.writestr("word/comments.xml", comments_xml)

    codebook = make_codebook(tmp_path, "SECRET==>MASKED\n")
    handler = DocxHandler()

    masked, count, _ = handler.mask(str(source), Masker(codebook))
    restored, restored_count = handler.restore(masked, Restorer(codebook))

    # 通过 XML 直接验证（不走 Document.comments）
    def get_comment_info(docx_path):
        with zipfile.ZipFile(docx_path, "r") as z:
            xml_bytes = z.read("word/comments.xml")
        root = etree.fromstring(xml_bytes)
        nsmap = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        comment = root.find(".//w:comment", nsmap)
        text_nodes = [t.text for t in comment.findall(".//w:t", nsmap) if t.text]
        return {
            "author": comment.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}author"
            ),
            "initials": comment.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}initials"
            ),
            "text": "".join(text_nodes),
        }

    masked_info = get_comment_info(masked)
    restored_info = get_comment_info(restored)

    assert count == 2  # "SECRET" in text + author
    assert masked_info["text"] == "MASKED comment"
    assert masked_info["author"] == "MASKED"
    assert restored_count == 2
    assert restored_info["text"] == "SECRET comment"
    assert restored_info["author"] == "SECRET"


def test_docx_unsupported_text_part_emits_warning_without_leaking_value(tmp_path):
    codebook = make_codebook(tmp_path, "SECRET==>MASKED\n")
    chart_xml = (
        b'<c:chart xmlns:c="urn:chart" xmlns:a="urn:drawing">'
        b'<a:t>SECRET</a:t></c:chart>'
    )
    part = SimpleNamespace(
        partname="/word/charts/chart1.xml", blob=chart_xml, rels={}
    )
    doc = SimpleNamespace(
        part=SimpleNamespace(package=SimpleNamespace(parts=[part]))
    )
    warnings = DocxHandler()._scan_unsupported_parts(doc, Masker(codebook), original_texts={"SECRET"})
    assert warnings == ["不支持的 OPC 文本部件可能含敏感内容：word/charts/chart1.xml"]
    assert "SECRET" not in warnings[0]


def test_single_pass_folder_scan_returns_skipped_and_progress(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.pdf").write_text("b", encoding="utf-8")
    progress = []
    files, skipped, errors = scan_files(
        str(tmp_path), ["txt"], progress_callback=lambda count, path: progress.append((count, path))
    )
    assert [Path(path).name for path in files] == ["a.txt"]
    assert skipped == 1
    assert errors == []
    assert progress


def test_custom_output_directory_is_execution_precondition(tmp_path):
    state = AppState()
    state.codebook.valid = True
    source = tmp_path / "a.txt"
    source.write_text("a", encoding="utf-8")
    state.files = [create_file_item(str(source))]
    state.output_same_dir = False
    state.output_dir = None
    assert state.can_execute is False
    state.output_dir = str(tmp_path)
    assert state.can_execute is True


def test_results_empty_state_resets_all_cards(monkeypatch):
    class Card:
        def __init__(self):
            self.value = "stale"

        def set_value(self, value):
            self.value = value

    class Scroll:
        def winfo_children(self):
            return []

        content = SimpleNamespace(winfo_children=lambda: [])

    class Label:
        def __init__(self, *_args, **_kwargs):
            pass

        def pack(self, **_kwargs):
            pass

    monkeypatch.setattr("docmask.ui.pages.results_page.ctk.CTkLabel", Label)
    page = SimpleNamespace(
        state=AppState(),
        _list_scroll=Scroll(),
        _card_total=Card(),
        _card_success=Card(),
        _card_fail=Card(),
        _card_replacements=Card(),
    )
    ResultsPage._refresh(page)
    assert {
        page._card_total.value,
        page._card_success.value,
        page._card_fail.value,
        page._card_replacements.value,
    } == {"0"}
