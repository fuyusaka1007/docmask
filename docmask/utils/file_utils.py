"""文件操作工具"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def user_data_dir() -> Path:
    """跨平台用户数据目录（设置、日志、诊断等持久化文件的根目录）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DocMask"
    elif sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "DocMask"
        return Path.home() / "AppData" / "Local" / "DocMask"
    else:
        return Path.home() / ".local" / "share" / "docmask"


def generate_output_path(
    input_path: str,
    output_dir: str | None = None,
    suffix: str = "_desensitized",
    auto_increment: bool = True,
    output_extension: str | None = None,
) -> str:
    """
    生成输出文件路径
    - 若指定 output_dir，则输出到该目录
    - 否则输出到输入文件同目录，文件名添加后缀
    - 若 auto_increment=True 且输出文件已存在，自动追加序号
    """
    input_file = Path(input_path)
    stem = input_file.stem
    ext = output_extension or input_file.suffix
    if ext and not ext.startswith("."):
        ext = f".{ext}"

    if output_dir:
        base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        output_file = base_dir / f"{stem}{suffix}{ext}"
    else:
        output_file = input_file.parent / f"{stem}{suffix}{ext}"

    if auto_increment and output_file.exists():
        counter = 1
        while True:
            if output_dir:
                output_file = base_dir / f"{stem}{suffix}_{counter}{ext}"
            else:
                output_file = input_file.parent / f"{stem}{suffix}_{counter}{ext}"
            if not output_file.exists():
                break
            counter += 1

    return str(output_file)


def ensure_dir(dirpath: str) -> None:
    """确保目录存在，不存在则创建"""
    Path(dirpath).mkdir(parents=True, exist_ok=True)


def _next_available_path(path: Path) -> Path:
    """返回不覆盖现有文件的路径。"""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_output_path(
    input_path: str,
    output: str | None,
    *,
    suffix: str,
    batch_mode: bool,
    output_extension: str | None = None,
) -> str:
    """统一解析 CLI 输出语义，并保证返回路径不会覆盖现有文件。

    批处理时 ``output`` 只能是目录；单文件时可传文件或目录。单文件中，
    已存在目录或无扩展名的新路径按目录处理，有扩展名的新路径按文件处理。
    """
    if output is None:
        return generate_output_path(
            input_path, suffix=suffix, output_extension=output_extension
        )

    requested = Path(output).expanduser()
    if batch_mode:
        if requested.exists() and not requested.is_dir():
            raise ValueError("批量处理时 --output 必须是目录，不能是文件")
        requested.mkdir(parents=True, exist_ok=True)
        return generate_output_path(
            input_path,
            output_dir=str(requested),
            suffix=suffix,
            output_extension=output_extension,
        )

    is_directory = requested.is_dir() if requested.exists() else not requested.suffix
    if is_directory:
        requested.mkdir(parents=True, exist_ok=True)
        return generate_output_path(
            input_path,
            output_dir=str(requested),
            suffix=suffix,
            output_extension=output_extension,
        )

    requested.parent.mkdir(parents=True, exist_ok=True)
    if output_extension:
        extension = output_extension if output_extension.startswith(".") else f".{output_extension}"
        requested = requested.with_suffix(extension)
    return str(_next_available_path(requested))


@contextmanager
def staged_output_path(final_path: str) -> Iterator[str]:
    """在目标同目录写临时文件，成功后以不覆盖方式提交。"""
    final = Path(final_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(f"拒绝覆盖已有文件：{final}")

    handle, temp_name = tempfile.mkstemp(
        prefix=f".{final.stem}.", suffix=f".tmp{final.suffix}", dir=str(final.parent)
    )
    os.close(handle)
    temp = Path(temp_name)
    try:
        yield str(temp)
        if not temp.is_file():
            raise OSError("处理器未生成临时输出文件")
        # hard-link 创建目标是原子的，且目标已存在时必然失败，不会覆盖。
        os.link(temp, final)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
