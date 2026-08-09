"""任务结果页面：展示处理结果摘要与文件状态"""
import os
import subprocess
import sys
import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_TITLE, FS_SECTION, FS_BODY, FS_SMALL, FS_STAT,
    S_2, S_3, S_4, S_5, S_6, BTN_HEIGHT_SM,
    RADIUS_BTN, RADIUS_CARD,
    BG_PAGE, BG_CARD, BORDER, FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, WARNING, ERROR, INFO,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
    TAG_DOCX, TAG_DOC, TAG_TXT,
    BG_TAG_DOCX, BG_TAG_DOC, BG_TAG_TXT,
    MAX_WIDTH_RESULTS,
)
from docmask.ui.state import AppState, FileStatus, FileItem
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.status_badge import StatusBadge
from docmask.ui.widgets.scroll_frame import PageScrollFrame

_FMT_TAG = {
    "docx": (TAG_DOCX, BG_TAG_DOCX),
    "doc": (TAG_DOC, BG_TAG_DOC),
    "txt": (TAG_TXT, BG_TAG_TXT),
}


class ResultRow(ctk.CTkFrame):
    """结果列表行"""

    def __init__(self, master, item: FileItem, **kwargs):
        super().__init__(master, fg_color=BG_CARD, corner_radius=6, **kwargs)

        # 文件名
        name = item.filename
        if len(name) > 35:
            name = name[:32] + "..."

        ctk.CTkLabel(
            self, text=name, font=font(FS_BODY),
            text_color=FG_MAIN, anchor="w",
        ).pack(side="left", padx=(S_3, S_2), fill="x", expand=True)

        # 格式
        fg, bg = _FMT_TAG.get(item.fmt, (FG_MUTED, BORDER))
        ctk.CTkLabel(
            self, text=item.fmt.upper(),
            font=font(FS_SMALL, "bold"),
            text_color=fg, fg_color=bg,
            corner_radius=10, padx=8, height=20,
        ).pack(side="left", padx=S_2)

        # 状态
        status_colors = {
            FileStatus.DONE: SUCCESS,
            FileStatus.CONFLICT: WARNING,
            FileStatus.FAILED: ERROR,
            FileStatus.STOPPED: FG_MUTED,
        }
        StatusBadge(self, status=item.status).pack(side="left", padx=S_2)

        # 替换次数
        count_text = f"{item.replacements}" if item.status == FileStatus.DONE else "--"
        ctk.CTkLabel(
            self, text=count_text,
            font=font(FS_SMALL), text_color=FG_MUTED,
            width=50, anchor="e",
        ).pack(side="left", padx=S_2)

        # 操作按钮
        if item.status == FileStatus.DONE and item.output_path:
            ctk.CTkButton(
                self, text="打开目录",
                font=font(FS_SMALL),
                width=60, height=24,
                corner_radius=RADIUS_BTN,
                fg_color="transparent",
                text_color=PRIMARY,
                hover_color=BG_INFO,
                command=lambda: self._open_dir(item.output_path),
            ).pack(side="right", padx=(S_2, S_3))

    def _open_dir(self, path: str):
        """在系统文件管理器中打开文件所在目录"""
        dirname = os.path.dirname(path) or "."
        if sys.platform == "darwin":
            subprocess.Popen(["open", dirname])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", dirname])
        else:
            subprocess.Popen(["xdg-open", dirname])


class SummaryCard(ctk.CTkFrame):
    """统计卡片"""

    def __init__(self, master, label: str, value: str, color, **kwargs):
        super().__init__(
            master, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
            **kwargs,
        )

        self._value_label = ctk.CTkLabel(
            self, text=value,
            font=font(FS_STAT, "bold"),
            text_color=color,
        )
        self._value_label.pack(anchor="w", padx=S_4, pady=(S_4, 0))

        ctk.CTkLabel(
            self, text=label,
            font=font(FS_SMALL),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(anchor="w", padx=S_4, pady=(0, S_4))

    def set_value(self, value: str):
        self._value_label.configure(text=value)


class ResultsPage(ctk.CTkFrame):
    """任务结果页面"""

    def __init__(self, master, state: AppState, controller, on_navigate: callable = None, **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate

        self._build()

    def _build(self):
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=S_6, pady=S_5)

        # 标题
        header = ctk.CTkFrame(self._content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_2))

        ctk.CTkLabel(
            header, text="任务结果",
            font=font(20, "bold"),
            text_color=FG_MAIN,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            header, text="查看处理结果、失败原因与覆盖率",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(anchor="w")

        # 统计卡片
        stats_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        stats_frame.pack(fill="x", pady=S_4)

        self._card_total = SummaryCard(stats_frame, "总文件", "0", FG_MAIN)
        self._card_total.pack(side="left", fill="x", expand=True, padx=(0, S_3))

        self._card_success = SummaryCard(stats_frame, "成功", "0", SUCCESS)
        self._card_success.pack(side="left", fill="x", expand=True, padx=(0, S_3))

        self._card_fail = SummaryCard(stats_frame, "冲突/失败", "0", ERROR)
        self._card_fail.pack(side="left", fill="x", expand=True, padx=(0, S_3))

        # A-18: 增加已停止统计卡片
        self._card_stopped = SummaryCard(stats_frame, "已停止", "0", FG_MUTED)
        self._card_stopped.pack(side="left", fill="x", expand=True, padx=(0, S_3))

        self._card_replacements = SummaryCard(stats_frame, "替换总数", "0", PRIMARY)
        self._card_replacements.pack(side="left", fill="x", expand=True)

        # 文件列表
        list_card = ctk.CTkFrame(
            self._content, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        list_card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            list_card, text="文件列表",
            font=font(FS_SMALL, "bold"),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(fill="x", padx=S_4, pady=(S_4, S_3))

        self._list_scroll = PageScrollFrame(
            list_card, fg_color="transparent",
            corner_radius=0,
        )
        self._list_scroll.pack(fill="both", expand=True, padx=S_3, pady=(0, S_4))

        # 空状态
        self._empty_label = ctk.CTkLabel(
            self._list_scroll.content,
            text="完成一次任务后，结果会显示在这里",
            font=font(FS_BODY),
            text_color=FG_SUBTLE,
        )
        self._empty_label.pack(pady=40)

    def on_show(self):
        """页面被显示时刷新结果"""
        self._refresh()

    def _refresh(self):
        """刷新结果列表"""
        # 清除旧内容
        for child in self._list_scroll.content.winfo_children():
            child.destroy()

        files = self.state.files

        # 先重置，避免从有结果状态切换为空队列时残留旧统计。
        self._card_total.set_value("0")
        self._card_success.set_value("0")
        self._card_fail.set_value("0")
        self._card_stopped.set_value("0")
        self._card_replacements.set_value("0")

        if not files:
            self._empty_label = ctk.CTkLabel(
                self._list_scroll.content,
                text="完成一次任务后，结果会显示在这里",
                font=font(FS_BODY),
                text_color=FG_SUBTLE,
            )
            self._empty_label.pack(pady=40)
        else:
            # 统计
            total = len(files)
            success = sum(1 for f in files if f.status == FileStatus.DONE)
            failed = sum(1 for f in files if f.status in (FileStatus.FAILED, FileStatus.CONFLICT))
            stopped = sum(1 for f in files if f.status == FileStatus.STOPPED)
            replacements = sum(f.replacements for f in files)

            # 更新统计卡片
            self._card_total.set_value(str(total))
            self._card_success.set_value(str(success))
            self._card_fail.set_value(str(failed))
            self._card_stopped.set_value(str(stopped))
            self._card_replacements.set_value(str(replacements))

            # 文件行
            for item in files:
                row = ResultRow(self._list_scroll.content, item=item)
                row.pack(fill="x", pady=1)

            # 显示失败/冲突详情
            for item in files:
                if item.status in (FileStatus.FAILED, FileStatus.CONFLICT) or item.warnings:
                    detail_text = item.error_message or item.conflict_details or ""
                    if item.warnings:
                        warning_text = "；".join(item.warnings)
                        detail_text = f"{detail_text}；{warning_text}" if detail_text else warning_text
                    if detail_text:
                        detail_frame = ctk.CTkFrame(
                            self._list_scroll.content, fg_color="transparent",
                        )
                        detail_frame.pack(fill="x", pady=(0, S_2))

                        ctk.CTkLabel(
                            detail_frame,
                            text=f"  {item.filename}: {detail_text[:100]}",
                            font=font(FS_SMALL),
                            text_color=WARNING if item.warnings else FG_MUTED,
                            anchor="w", justify="left",
                            wraplength=600,
                        ).pack(anchor="w")
