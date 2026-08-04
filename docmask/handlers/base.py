"""Handler 基础接口：进度回调与任务取消

为所有 Handler 提供统一的进度报告和取消机制。
UI 层通过 CancelToken 控制任务取消，通过 progress_callback 接收实时进度。
"""
import threading
from typing import Callable, Optional


class CancelToken:
    """线程安全的任务取消标记

    UI 主线程调用 cancel() 请求取消；
    Handler 在检查点调用 is_cancelled 查询状态。
    """

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        """请求取消任务"""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """是否已请求取消"""
        return self._event.is_set()


class TaskCancelledError(Exception):
    """任务被用户取消时抛出"""


# 进度回调签名: (当前步骤, 总步骤数, 描述信息) -> None
#   current: 已完成的步骤数（0 ~ total）
#   total:   总步骤数
#   message: 当前步骤的描述文本
ProgressCallback = Callable[[int, int, str], None]


def check_cancel(token: Optional[CancelToken]) -> None:
    """检查取消标记，若已取消则抛出 TaskCancelledError

    Handler 在各元素处理之间的检查点调用此函数。
    """
    if token is not None and token.is_cancelled:
        raise TaskCancelledError("任务已被用户取消")


def report_progress(
    callback: Optional[ProgressCallback],
    current: int,
    total: int,
    message: str,
) -> None:
    """安全调用进度回调，callback 为 None 时跳过"""
    if callback is not None:
        callback(current, total, message)
