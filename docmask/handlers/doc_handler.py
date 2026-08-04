""".doc 文件处理器：安全转换为 .docx 后委托 DocxHandler。"""
from __future__ import annotations

import logging
import gc
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from docmask.core.masker import Masker
from docmask.core.restorer import Restorer
from docmask.handlers.docx_handler import DocxHandler
from docmask.handlers.base import (
    CancelToken,
    ProgressCallback,
    check_cancel,
    report_progress,
)
from docmask.utils.file_utils import generate_output_path
from docmask.config import DESENSITIZED_SUFFIX, RESTORED_SUFFIX

logger = logging.getLogger(__name__)


class DocHandler:
    """.doc 文件处理器：转换为 DOCX、处理，并输出合法的 .docx 文件。"""

    def __init__(self):
        self._docx_handler = DocxHandler()

    @property
    def last_warnings(self) -> list[str]:
        return list(self._docx_handler.last_warnings)

    @staticmethod
    def _is_valid_docx(path: str | Path) -> bool:
        """验证转换结果至少是可读取的 OOXML ZIP 包。"""
        candidate = Path(path)
        return candidate.is_file() and candidate.stat().st_size > 0 and zipfile.is_zipfile(candidate)

    def _convert_to_docx(self, input_path: str, temp_dir: str) -> str:
        """将 .doc 转换为 .docx，并返回转换器实际生成的文件路径。"""
        output_path = Path(temp_dir) / f"{Path(input_path).stem}.docx"

        converted = self._try_pywin32_convert(input_path, output_path)
        if converted is not None:
            return str(converted)

        converted = self._try_libreoffice_convert(input_path, output_path)
        if converted is not None:
            return str(converted)

        raise RuntimeError(
            "无法转换 .doc 文件。请安装以下任一工具：\n"
            "  - Microsoft Word（Windows 推荐）\n"
            "  - LibreOffice（跨平台）\n"
            "  或手动将 .doc 另存为 .docx 后重试。"
        )

    def _try_pywin32_convert(self, input_path: str, output_path: Path) -> Path | None:
        """尝试使用独立 Word COM 实例转换，异常时保证释放全部资源。"""
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            logger.debug("pywin32 未安装")
            return None

        word = None
        document = None
        com_initialized = False
        word_pid = None
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            word = win32com.client.DispatchEx("Word.Application")
            try:
                import win32process
                word_pid = win32process.GetWindowThreadProcessId(word.Hwnd)[1]
            except Exception:
                logger.debug("无法获取独立 Word 实例 PID")
            word.Visible = False
            word.DisplayAlerts = 0
            try:
                word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
            except Exception:
                logger.debug("无法设置 Word 宏安全级别")
            document = word.Documents.Open(
                os.path.abspath(input_path),
                ReadOnly=True,
                AddToRecentFiles=False,
            )
            document.SaveAs2(os.path.abspath(output_path), FileFormat=16)
            if not self._is_valid_docx(output_path):
                raise RuntimeError("Word 未生成有效的 DOCX 文件")
            logger.info("通过 Microsoft Word 转换: %s", input_path)
            return output_path
        except Exception as exc:
            logger.warning("Microsoft Word 转换失败: %s", exc)
            return None
        finally:
            if document is not None:
                try:
                    document.Close(SaveChanges=False)
                except Exception as exc:
                    logger.debug("关闭 Word 文档失败: %s", exc)
                document = None
            if word is not None:
                try:
                    word.Quit()
                except Exception as exc:
                    logger.debug("退出 Word 失败: %s", exc)
                word = None
            gc.collect()
            if com_initialized:
                pythoncom.CoUninitialize()
            gc.collect()
            if word_pid:
                self._wait_for_windows_process_exit(word_pid)

    @staticmethod
    def _wait_for_windows_process_exit(process_id: int, timeout_ms: int = 20000) -> None:
        """等待本任务创建的 Word 进程退出；超时后只终止该独立实例。"""
        if os.name != "nt":
            return
        try:
            import ctypes

            synchronize = 0x00100000
            process_terminate = 0x0001
            wait_timeout = 0x00000102
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                synchronize | process_terminate, False, process_id
            )
            if not handle:
                return
            try:
                result = kernel32.WaitForSingleObject(handle, timeout_ms)
                if result == wait_timeout:
                    logger.warning(
                        "独立 Word 实例 %s 未按时退出，执行定向终止", process_id
                    )
                    kernel32.TerminateProcess(handle, 1)
                    kernel32.WaitForSingleObject(handle, 5000)
            finally:
                kernel32.CloseHandle(handle)
        except Exception as exc:
            logger.debug("等待 Word 进程退出失败: %s", exc)

    def _try_libreoffice_convert(self, input_path: str, output_path: Path) -> Path | None:
        """尝试使用 LibreOffice 命令行转换，并返回真实输出路径。"""
        try:
            command = self._find_libreoffice_command()
            if command is None:
                logger.debug("LibreOffice 未安装")
                return None

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="docmask_lo_profile_") as profile_dir:
                profile_uri = Path(profile_dir).resolve().as_uri()
                result = subprocess.run(
                    [
                        command,
                        f"-env:UserInstallation={profile_uri}",
                        "--headless",
                        "--nologo",
                        "--nodefault",
                        "--nofirststartwizard",
                        "--nolockcheck",
                        "--norestore",
                        "--convert-to", "docx:Office Open XML Text",
                        "--outdir", str(output_path.parent),
                        os.path.abspath(input_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

            generated = output_path.parent / f"{Path(input_path).stem}.docx"
            if result.returncode == 0 and self._is_valid_docx(generated):
                logger.info("通过 LibreOffice 转换: %s", input_path)
                return generated

            detail = (result.stderr or result.stdout or "未生成有效 DOCX").strip()
            logger.debug("LibreOffice 转换失败: %s", detail)
        except FileNotFoundError:
            logger.debug("LibreOffice 未安装")
        except subprocess.TimeoutExpired:
            logger.warning("LibreOffice 转换超时")
        except Exception as exc:
            logger.warning("LibreOffice 转换失败: %s", exc)
        return None

    @staticmethod
    def _find_libreoffice_command() -> str | None:
        """定位 LibreOffice CLI，兼容安装程序未将其加入 PATH 的情况。"""
        for command_name in ("soffice", "libreoffice"):
            resolved = shutil.which(command_name)
            if resolved:
                return resolved

        candidates = (
            Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
            Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path("/usr/bin/libreoffice"),
            Path("/usr/bin/soffice"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def _resolve_docx_output_path(
        input_path: str,
        output_path: Optional[str],
        suffix: str,
    ) -> str:
        """确保 .doc 处理结果始终写入扩展名正确的 DOCX 文件。"""
        if output_path is None:
            return generate_output_path(
                input_path,
                suffix=suffix,
                output_extension=".docx",
            )

        candidate = Path(output_path)
        if candidate.is_dir():
            return generate_output_path(
                input_path,
                output_dir=str(candidate),
                suffix=suffix,
                output_extension=".docx",
            )
        if candidate.suffix.lower() != ".docx":
            candidate = candidate.with_suffix(".docx")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return str(candidate)

    def mask(
        self,
        input_path: str,
        masker: Masker,
        output_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> tuple[str, int, dict]:
        """脱敏 .doc，输出一个合法的 .docx 文件。"""
        total_steps = 10
        report_progress(progress_callback, 0, total_steps, "正在转换 .doc 文件...")
        check_cancel(cancel_token)

        resolved_output = self._resolve_docx_output_path(
            input_path, output_path, DESENSITIZED_SUFFIX,
        )
        with tempfile.TemporaryDirectory(prefix="docmask_doc_") as temp_dir:
            tmp_docx = self._convert_to_docx(input_path, temp_dir)
            report_progress(progress_callback, 1, total_steps, "文件转换完成")

            def _wrapped(inner_current: int, inner_total: int, message: str):
                report_progress(progress_callback, 1 + inner_current, total_steps, message)

            return self._docx_handler.mask(
                tmp_docx,
                masker,
                resolved_output,
                progress_callback=_wrapped,
                cancel_token=cancel_token,
            )

    def restore(
        self,
        input_path: str,
        restorer: Restorer,
        output_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> tuple[str, int]:
        """恢复 .doc，输出一个合法的 .docx 文件。"""
        total_steps = 9
        report_progress(progress_callback, 0, total_steps, "正在转换 .doc 文件...")
        check_cancel(cancel_token)

        resolved_output = self._resolve_docx_output_path(
            input_path, output_path, RESTORED_SUFFIX,
        )
        with tempfile.TemporaryDirectory(prefix="docmask_doc_") as temp_dir:
            tmp_docx = self._convert_to_docx(input_path, temp_dir)
            report_progress(progress_callback, 1, total_steps, "文件转换完成")

            def _wrapped(inner_current: int, inner_total: int, message: str):
                report_progress(progress_callback, 1 + inner_current, total_steps, message)

            return self._docx_handler.restore(
                tmp_docx,
                restorer,
                resolved_output,
                progress_callback=_wrapped,
                cancel_token=cancel_token,
            )
