"""用真实旧版 DOC 验证 Word/LibreOffice 转换与 mask→restore 往返。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import site
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
site.addsitedir(str(PROJECT_ROOT / ".test_runtime"))

from docmask.core.codebook import Codebook
from docmask.core.masker import Masker
from docmask.core.restorer import Restorer
from docmask.handlers.doc_handler import DocHandler
from docmask.handlers.docx_handler import DocxHandler, NSMAP


OFFICE_PROCESS_NAMES = {"winword.exe", "soffice.exe", "soffice.bin"}
TEMP_PATTERNS = ("docmask_doc_*", "docmask_lo_profile_*")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _office_processes() -> dict[int, str]:
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
        check=True,
    )
    processes: dict[int, str] = {}
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 2:
            continue
        image_name = row[0].lower()
        if image_name not in OFFICE_PROCESS_NAMES:
            continue
        try:
            processes[int(row[1])] = image_name
        except ValueError:
            continue
    return processes


def _wait_for_process_cleanup(baseline: dict[int, str], timeout: float = 15.0) -> dict[int, str]:
    deadline = time.monotonic() + timeout
    new_processes: dict[int, str] = {}
    while time.monotonic() < deadline:
        current = _office_processes()
        new_processes = {
            process_id: name
            for process_id, name in current.items()
            if process_id not in baseline
        }
        if not new_processes:
            return {}
        time.sleep(0.5)
    return new_processes


def _temp_directories() -> set[str]:
    temp_root = Path(tempfile.gettempdir())
    matches: set[str] = set()
    for pattern in TEMP_PATTERNS:
        matches.update(str(path.resolve()) for path in temp_root.glob(pattern))
    return matches


def _visible_text(path: Path) -> str:
    chunks: list[str] = []
    with ZipFile(path) as package:
        for member in sorted(package.namelist()):
            if not member.startswith("word/") or not member.endswith(".xml"):
                continue
            try:
                root = etree.fromstring(package.read(member))
            except etree.XMLSyntaxError:
                continue
            chunks.extend(node.text or "" for node in root.findall(".//w:t", NSMAP))
    return "".join(chunks)


def _build_isolated_codebook(source_path: Path, output_path: Path) -> int:
    """保留精确匹配原词，生成不与真实文稿冲突的测试专用替换词。"""
    source_codebook = Codebook(str(source_path))
    source_codebook.load()
    token_alphabet = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黄"
    lines = ["# 真实 DOC 隔离集成测试专用；不包含不可逆正则规则"]
    for index, original in enumerate(source_codebook.forward_map):
        high, low = divmod(index, len(token_alphabet))
        replacement = f"隐{token_alphabet[high]}{token_alphabet[low]}"
        lines.append(f"{original}==>{replacement}")
    if len(lines) == 1:
        raise RuntimeError("源密码本没有可用于往返验证的精确匹配规则")
    output_path.parent.mkdir(parents=True, exist_ok=False)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def _run_engine(
    engine: str,
    isolated_doc: Path,
    output_dir: Path,
    codebook_path: Path,
    baseline_processes: dict[int, str],
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    converted_path = output_dir / f"{isolated_doc.stem}.docx"
    handler = DocHandler()

    started_at = time.monotonic()
    if engine == "word":
        converted = handler._try_pywin32_convert(str(isolated_doc), converted_path)
    elif engine == "libreoffice":
        converted = handler._try_libreoffice_convert(str(isolated_doc), converted_path)
    else:
        raise ValueError(f"Unsupported engine: {engine}")

    if converted is None:
        raise RuntimeError(f"{engine} 未生成有效 DOCX")
    converted_path = Path(converted)

    codebook = Codebook(str(codebook_path))
    codebook.load()
    docx_handler = DocxHandler()
    masked_path, masked_count, coverage = docx_handler.mask(
        str(converted_path),
        Masker(codebook),
        output_path=str(output_dir / "masked.docx"),
    )
    restored_path, restored_count = docx_handler.restore(
        masked_path,
        Restorer(codebook),
        output_path=str(output_dir / "restored.docx"),
    )

    converted_text = _visible_text(converted_path)
    masked_text = _visible_text(Path(masked_path))
    restored_text = _visible_text(Path(restored_path))
    residual_processes = _wait_for_process_cleanup(baseline_processes)
    checks = {
        "converted_docx_valid": DocHandler._is_valid_docx(converted_path),
        "masked_docx_valid": DocHandler._is_valid_docx(masked_path),
        "restored_docx_valid": DocHandler._is_valid_docx(restored_path),
        "mask_replacements_positive": masked_count > 0,
        "restore_count_matches_mask": restored_count == masked_count,
        "masked_text_differs_from_converted": masked_text != converted_text,
        "restored_text_matches_converted": restored_text == converted_text,
        "no_new_office_processes": not residual_processes,
    }
    return {
        "engine": engine,
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "converted": str(converted_path),
        "masked": str(Path(masked_path)),
        "restored": str(Path(restored_path)),
        "mask_replacements": masked_count,
        "restore_replacements": restored_count,
        "coverage": coverage,
        "residual_processes": residual_processes,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--codebook", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    workspace = Path(args.workspace).resolve()
    codebook_path = Path(args.codebook).resolve()
    if workspace.exists():
        raise FileExistsError(f"隔离工作区已存在: {workspace}")
    workspace.mkdir(parents=True)
    input_dir = workspace / "input"
    input_dir.mkdir()
    isolated_doc = input_dir / source.name

    source_stat_before = source.stat()
    source_hash_before = _sha256(source)
    shutil.copyfile(source, isolated_doc)
    isolated_codebook_path = workspace / "config" / "integration-codebook.txt"
    isolated_rule_count = _build_isolated_codebook(codebook_path, isolated_codebook_path)
    baseline_processes = _office_processes()
    temp_before = _temp_directories()

    engines: dict[str, dict] = {}
    for engine in ("word", "libreoffice"):
        try:
            engines[engine] = _run_engine(
                engine,
                isolated_doc,
                workspace / engine,
                isolated_codebook_path,
                baseline_processes,
            )
        except Exception as exc:
            engines[engine] = {
                "engine": engine,
                "error": f"{type(exc).__name__}: {exc}",
                "passed": False,
            }

    temp_after = _temp_directories()
    source_stat_after = source.stat()
    source_hash_after = _sha256(source)
    final_processes = _office_processes()
    new_final_processes = {
        process_id: name
        for process_id, name in final_processes.items()
        if process_id not in baseline_processes
    }
    isolation_checks = {
        "source_hash_unchanged": source_hash_after == source_hash_before,
        "source_size_unchanged": source_stat_after.st_size == source_stat_before.st_size,
        "source_mtime_unchanged": source_stat_after.st_mtime_ns == source_stat_before.st_mtime_ns,
        "isolated_copy_matches_source": _sha256(isolated_doc) == source_hash_before,
        "no_new_temp_directories": temp_after == temp_before,
        "no_new_office_processes": not new_final_processes,
    }
    passed = all(result.get("passed", False) for result in engines.values()) and all(
        isolation_checks.values()
    )
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source),
            "size": source_stat_before.st_size,
            "sha256_before": source_hash_before,
            "sha256_after": source_hash_after,
        },
        "workspace": str(workspace),
        "isolated_codebook": {
            "path": str(isolated_codebook_path),
            "exact_rule_count": isolated_rule_count,
            "source_codebook_unchanged": str(codebook_path),
        },
        "baseline_processes": baseline_processes,
        "final_processes": final_processes,
        "new_final_processes": new_final_processes,
        "temp_directories_before": sorted(temp_before),
        "temp_directories_after": sorted(temp_after),
        "engines": engines,
        "isolation_checks": isolation_checks,
        "passed": passed,
    }
    result_path = workspace / "real-doc-integration-result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
