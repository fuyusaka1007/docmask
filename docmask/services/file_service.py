"""文件收集与 Handler 选择公共服务

供 CLI 和 UI 共用，避免重复实现文件遍历和 Handler 分发逻辑。
"""
import os
from pathlib import Path
from typing import Callable, Optional

from docmask.config import DEFAULT_FORMATS
from docmask.handlers.txt_handler import TxtHandler
from docmask.handlers.docx_handler import DocxHandler
from docmask.handlers.doc_handler import DocHandler


def collect_files(
    input_path: str,
    formats: Optional[list[str]] = None,
    recursive: bool = True,
) -> tuple[list[str], list[str]]:
    """收集待处理的文件列表

    - input_path 为文件时：若格式匹配则返回该文件，否则返回空列表
    - input_path 为目录时：递归或非递归扫描目录下匹配格式的文件

    Args:
        input_path: 输入文件或目录路径
        formats: 允许的格式列表（不含点号，如 ['docx', 'txt']），默认 DEFAULT_FORMATS
        recursive: 目录模式下是否递归子目录

    Returns:
        (排序后的文件路径列表, 访问错误列表)

    A-16: 不再丢弃 scan_files() 返回的访问错误，向上传递。
    """
    files, _skipped, errors = scan_files(
        input_path, formats=formats, recursive=recursive
    )
    return files, errors


def scan_files(
    input_path: str,
    formats: Optional[list[str]] = None,
    recursive: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> tuple[list[str], int, list[str]]:
    """单次遍历目录，返回（支持文件、跳过数、权限/访问错误）。"""
    if formats is None:
        formats = DEFAULT_FORMATS
    normalized = {f.strip().lower().lstrip(".") for f in formats}

    if os.path.isfile(input_path):
        ext = Path(input_path).suffix.lower().lstrip(".")
        if ext in normalized:
            return [input_path], 0, []
        return [], 1, []

    if not os.path.isdir(input_path):
        return [], 0, []

    files: list[str] = []
    skipped = 0
    errors: list[str] = []
    visited = 0

    def onerror(error: OSError) -> None:
        errors.append(f"{getattr(error, 'filename', input_path)}: {error.strerror or error}")

    for root, dirs, names in os.walk(input_path, topdown=True, onerror=onerror):
        if cancel_check and cancel_check():
            break
        if not recursive:
            dirs.clear()
        for name in names:
            if cancel_check and cancel_check():
                return sorted(files), skipped, errors
            visited += 1
            path = os.path.join(root, name)
            ext = Path(name).suffix.lower().lstrip(".")
            if ext in normalized:
                files.append(path)
            else:
                skipped += 1
            if progress_callback and (visited == 1 or visited % 100 == 0):
                progress_callback(visited, path)
    return sorted(files), skipped, errors


def get_handler(filepath: str):
    """根据文件扩展名获取对应的处理器

    Returns:
        (handler_instance, format_str) — 不支持的格式返回 (None, ext)
    """
    ext = Path(filepath).suffix.lower()
    if ext == ".txt":
        return TxtHandler(), "txt"
    elif ext == ".docx":
        return DocxHandler(), "docx"
    elif ext == ".doc":
        return DocHandler(), "doc"
    else:
        return None, ext
