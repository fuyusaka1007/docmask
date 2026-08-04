"""状态徽章组件：纯文字 badge pill 样式。"""
import customtkinter as ctk
from docmask.ui.theme import (
    font, FS_SMALL, S_2, RADIUS_PILL,
    SUCCESS, WARNING, ERROR, INFO, FG_MUTED,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
)
from docmask.ui.state import FileStatus

# 状态 → (文字色, 背景色, 文字)
_STATUS_MAP = {
    FileStatus.WAITING: (INFO, BG_INFO, "等待预检"),
    FileStatus.PROCESSING: (INFO, BG_INFO, "处理中"),
    FileStatus.DONE: (SUCCESS, BG_SUCCESS, "完成"),
    FileStatus.CONFLICT: (WARNING, BG_WARNING, "冲突"),
    FileStatus.FAILED: (ERROR, BG_ERROR, "失败"),
    FileStatus.STOPPED: (FG_MUTED, (("#EEF1F5", "#1E2A38")), "已停止"),
}


class StatusBadge(ctk.CTkFrame):
    """状态徽章：badge pill 样式"""

    def __init__(self, master, status: FileStatus = FileStatus.WAITING, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._label = ctk.CTkLabel(self, font=font(FS_SMALL))
        self._label.pack(side="left", padx=S_2)

        self.set_status(status)

    def set_status(self, status: FileStatus) -> None:
        text_color, bg_color, text = _STATUS_MAP.get(
            status, (FG_MUTED, ("#EEF1F5", "#1E2A38"), str(status))
        )
        self.configure(fg_color=bg_color, corner_radius=RADIUS_PILL)
        self._label.configure(text=text, text_color=text_color)
