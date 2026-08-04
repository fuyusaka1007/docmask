"""TXT 文件读写与脱敏/恢复"""
import logging
from typing import Optional

from docmask.core.masker import Masker, MaskConflictError
from docmask.core.restorer import Restorer
from docmask.utils.encoding import detect_encoding
from docmask.utils.file_utils import generate_output_path, staged_output_path
from docmask.config import DESENSITIZED_SUFFIX, RESTORED_SUFFIX
from docmask.handlers.base import (
    CancelToken,
    ProgressCallback,
    check_cancel,
    report_progress,
)

logger = logging.getLogger(__name__)


class TxtHandler:
    """TXT 文件读写与脱敏/恢复"""

    def read(self, filepath: str) -> str:
        """读取 txt 文件内容，自动检测编码

        使用 universal newlines 模式，CRLF/CR 统一归一化为 LF。
        """
        encoding = detect_encoding(filepath)
        logger.info(f"检测到文件编码: {encoding} ({filepath})")
        with open(filepath, "r", encoding=encoding) as f:
            return f.read()

    def write(self, filepath: str, content: str, encoding: str = "utf-8") -> None:
        """写入 txt 文件

        输出策略：统一使用 UTF-8 编码（无 BOM），换行符归一化为 LF。
        无论输入文件的原始编码（UTF-8/GBK/UTF-8-SIG 等），输出始终为
        UTF-8 编码、LF 换行的纯文本，确保跨平台一致性。
        """
        with open(filepath, "w", encoding=encoding, newline="") as f:
            f.write(content)
        logger.info(f"已写入: {filepath}")

    def mask(
        self,
        input_path: str,
        masker: Masker,
        output_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> tuple[str, int, dict]:
        """
        脱敏 txt 文件
        返回 (输出路径, 替换次数, 覆盖率统计)

        进度步骤共 3 步：读取文件、冲突预检+脱敏、写入输出
        """
        TOTAL_STEPS = 3

        report_progress(progress_callback, 0, TOTAL_STEPS, "正在读取文件...")
        check_cancel(cancel_token)
        content = self.read(input_path)

        report_progress(progress_callback, 1, TOTAL_STEPS, "正在执行冲突预检与脱敏...")
        check_cancel(cancel_token)
        # 文档级脱敏词冲突预检
        conflicts = masker.precheck_conflict(content)
        if conflicts:
            raise MaskConflictError(MaskConflictError.format(conflicts))

        masked_content, count, coverage = masker.mask_text(content)

        if output_path is None:
            output_path = generate_output_path(input_path, suffix=DESENSITIZED_SUFFIX)

        report_progress(progress_callback, 2, TOTAL_STEPS, "正在写入输出文件...")
        with staged_output_path(output_path) as temp_path:
            self.write(temp_path, masked_content)
        report_progress(progress_callback, 3, TOTAL_STEPS, "脱敏完成")

        logger.info(f"脱敏完成: {input_path} -> {output_path}, 替换 {count} 处")
        return output_path, count, coverage

    def restore(
        self,
        input_path: str,
        restorer: Restorer,
        output_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> tuple[str, int]:
        """
        恢复 txt 文件
        返回 (输出路径, 替换次数)

        进度步骤共 3 步：读取文件、恢复、写入输出
        """
        TOTAL_STEPS = 3

        report_progress(progress_callback, 0, TOTAL_STEPS, "正在读取文件...")
        check_cancel(cancel_token)
        content = self.read(input_path)

        report_progress(progress_callback, 1, TOTAL_STEPS, "正在执行恢复...")
        check_cancel(cancel_token)
        restored_content, count = restorer.restore_text(content)

        if output_path is None:
            output_path = generate_output_path(input_path, suffix=RESTORED_SUFFIX)

        report_progress(progress_callback, 2, TOTAL_STEPS, "正在写入输出文件...")
        with staged_output_path(output_path) as temp_path:
            self.write(temp_path, restored_content)
        report_progress(progress_callback, 3, TOTAL_STEPS, "恢复完成")

        logger.info(f"恢复完成: {input_path} -> {output_path}, 替换 {count} 处")
        return output_path, count
