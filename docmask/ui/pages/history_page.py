"""历史记录页面：查看脱敏/恢复操作记录、使用的密码本与处理结果"""
from __future__ import annotations

import os
import subprocess
import sys
from tkinter import messagebox

import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_BODY, FS_LABEL, FS_SMALL,
    S_2, S_3, S_4, S_5, S_6,
    RADIUS_CARD, RADIUS_BTN, RADIUS_PILL,
    BG_PAGE, BG_CARD, BORDER, BORDER_LIGHT,
    FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, WARNING, ERROR, INFO,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
    BTN_HEIGHT_SM,
)
from docmask.ui.state import AppState
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.scroll_frame import PageScrollFrame
from docmask.ui.widgets.dialogs import show_confirm
from docmask.services.history_store import HistoryEntry


# ======================== 常量映射 ========================

# 状态 -> (文字色, 背景色, 文字)
_STATUS_MAP = {
    "done":     (SUCCESS,  BG_SUCCESS,    "完成"),
    "conflict": (WARNING,  BG_WARNING,    "冲突"),
    "failed":   (ERROR,    BG_ERROR,      "失败"),
    "stopped":  (FG_MUTED, BORDER_LIGHT,  "已停止"),
}

# 模式 -> (文字色, 背景色, 标签)
_MODE_MAP = {
    "mask":    (PRIMARY, BG_INFO,    "脱敏"),
    "restore": (SUCCESS, BG_SUCCESS, "恢复"),
}

# 过滤器
_FILTERS = [
    ("all",     "全部"),
    ("mask",    "脱敏"),
    ("restore", "恢复"),
]

# 行悬停背景（浅 PRIMARY 色）
_HOVER_BG = BG_INFO


def _format_time(timestamp: str) -> str:
    """将 '2026-08-08T15:30:00' 格式化为 '08-08 15:30'"""
    try:
        date_part, time_part = timestamp.split("T", 1)
        return f"{date_part[5:]} {time_part[:5]}"
    except Exception:
        return timestamp


def _truncate(text: str, max_len: int = 30) -> str:
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


class HistoryPage(ctk.CTkFrame):
    """历史记录页面"""

    def __init__(self, master, state: AppState, controller,
                 on_navigate: callable = None, **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate

        self._filter = "all"
        self._entries: list[HistoryEntry] = []

        self._build()

    # ======================== 布局构建 ========================

    def _build(self):
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=S_6, pady=S_5)

        self._build_header()
        self._build_filter_bar()

        # 历史列表滚动容器
        self._list_scroll = PageScrollFrame(
            self._content, fg_color="transparent", corner_radius=0,
        )
        self._list_scroll.pack(fill="both", expand=True, pady=(S_3, 0))

    # -------------------- 页头 --------------------

    def _build_header(self):
        header = ctk.CTkFrame(self._content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_3))

        # 左侧：标题 + 副标题
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            title_box, text="历史记录",
            font=font(20, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box, text="查看脱敏/恢复操作记录、使用的密码本与处理结果",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 右侧：清空历史按钮（btn-danger 样式）
        ctk.CTkButton(
            header, text="清空历史",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=ERROR,
            border_color=BORDER, border_width=1,
            hover_color=BG_ERROR,
            image=get_ctk_image("trash", 16, ERROR),
            compound="left",
            command=self._on_clear_history,
        ).pack(side="right", anchor="n")

    # -------------------- 过滤栏 --------------------

    def _build_filter_bar(self):
        bar = ctk.CTkFrame(self._content, fg_color="transparent")
        bar.pack(fill="x", pady=(0, S_3))

        self._filter_btns: dict[str, ctk.CTkButton] = {}
        for key, label in _FILTERS:
            btn = ctk.CTkButton(
                bar, text=label,
                font=font(FS_SMALL),
                height=28, width=60,
                corner_radius=RADIUS_PILL,
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=(0, S_2))
            self._filter_btns[key] = btn

        self._apply_filter_styles()

    def _apply_filter_styles(self):
        """根据当前过滤项刷新 pill 样式。"""
        for key, btn in self._filter_btns.items():
            if key == self._filter:
                btn.configure(
                    fg_color=PRIMARY, text_color=PRIMARY_FG,
                    hover_color=PRIMARY_HOVER, border_width=0,
                )
            else:
                btn.configure(
                    fg_color=BG_CARD, text_color=FG_MUTED,
                    hover_color=BG_PAGE,
                    border_color=BORDER, border_width=1,
                )

    # ======================== 数据刷新 ========================

    def on_show(self):
        """页面被显示时刷新历史列表。"""
        self._refresh()

    def _refresh(self):
        self._entries = self.controller.query_history(limit=1000)
        self._render_list()

    def _render_list(self):
        # 清除旧内容
        for child in self._list_scroll.content.winfo_children():
            child.destroy()

        # 历史已关闭
        if not self.state.history_enabled:
            self._render_disabled_state()
            return

        # 按过滤项筛选
        if self._filter == "all":
            entries = self._entries
        else:
            entries = [e for e in self._entries if e.mode == self._filter]

        # 空状态
        if not entries:
            self._render_empty_state()
            return

        # 历史行
        for entry in entries:
            row = HistoryRow(
                self._list_scroll.content, entry=entry,
                on_detail=self._show_detail,
            )
            row.pack(fill="x")

        # 底部信息
        total = len(self._entries)
        ctk.CTkLabel(
            self._list_scroll.content,
            text=f"共 {total} 条记录，最多保留 1000 条",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
        ).pack(pady=S_4)

    # -------------------- 空状态 --------------------

    def _render_empty_state(self):
        empty = ctk.CTkFrame(self._list_scroll.content, fg_color="transparent")
        empty.pack(expand=True, pady=80)

        ctk.CTkLabel(
            empty, image=get_ctk_image("history", 32, FG_MUTED), text="",
        ).pack()

        ctk.CTkLabel(
            empty, text="尚无历史记录",
            font=font(FS_BODY, "bold"),
            text_color=FG_MUTED,
        ).pack(pady=(S_3, S_2))

        ctk.CTkLabel(
            empty, text="执行脱敏或恢复操作后，记录将自动出现在这里",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
        ).pack()

    def _render_disabled_state(self):
        """历史记录已关闭：INFO 卡片 + 前往设置按钮。"""
        card = ctk.CTkFrame(
            self._list_scroll.content,
            fg_color=BG_CARD, corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        card.pack(fill="x", pady=40, padx=S_4)

        # 左侧 INFO 色边条
        accent = ctk.CTkFrame(card, fg_color=INFO, corner_radius=0, width=4)
        accent.pack(side="left", fill="y")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=S_5, pady=S_5)

        # info 图标 + 文字
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(
            top, image=get_ctk_image("info", 20, INFO), text="",
        ).pack(side="left", padx=(0, S_3), anchor="center")

        text_box = ctk.CTkFrame(top, fg_color="transparent")
        text_box.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            text_box, text="历史记录已关闭",
            font=font(FS_BODY, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            text_box,
            text="在设置中关闭了历史记录功能，操作将不会被保存。",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w", justify="left",
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            body, text="前往设置",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("settings", 16, FG_MAIN),
            compound="left",
            command=self._navigate_settings,
        ).pack(anchor="w", pady=(S_4, 0))

    # ======================== 事件处理 ========================

    def _set_filter(self, key: str):
        if key == self._filter:
            return
        self._filter = key
        self._apply_filter_styles()
        self._render_list()

    def _on_clear_history(self):
        confirmed = show_confirm(
            self,
            title="清空历史记录",
            message="确定要清空所有历史记录吗？此操作不可撤销。",
            confirm_text="清空",
            cancel_text="取消",
            danger=True,
        )
        if not confirmed:
            return
        self.controller.clear_history()
        self._refresh()

    def _navigate_settings(self):
        if self.on_navigate:
            self.on_navigate("settings")

    def _show_detail(self, entry: HistoryEntry):
        if entry.status == "failed":
            title = "失败详情"
        elif entry.status == "conflict":
            title = "冲突详情"
        elif entry.status == "stopped":
            title = "停止详情"
        else:
            title = "详情"
        text = entry.error or "无详细信息"
        messagebox.showinfo(
            title, f"文件：{entry.input_filename}\n\n{text}", parent=self,
        )


# ======================== 历史记录行 ========================

class HistoryRow(ctk.CTkFrame):
    """历史记录单行：时间 / 文件名 / 模式 / 密码本 / 替换数 / 状态 / 操作"""

    def __init__(self, master, entry: HistoryEntry,
                 on_detail: callable = None, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)
        self._entry = entry
        self._on_detail = on_detail

        # 列索引: 0=时间 1=文件名 2=模式 3=密码本 4=替换数 5=状态 6=操作
        self.grid_columnconfigure(1, weight=1)

        self._col_time(entry)
        self._col_filename(entry)
        self._col_mode(entry)
        self._col_codebook(entry)
        self._col_replacements(entry)
        self._col_status(entry)
        self._col_action(entry)

        # 底部分隔线
        ctk.CTkFrame(
            self, height=1, fg_color=BORDER_LIGHT, corner_radius=0,
        ).grid(row=1, column=0, columnspan=7, sticky="ew")

        # 悬停效果
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    # -------------------- 列构建 --------------------

    def _col_time(self, entry: HistoryEntry):
        ctk.CTkLabel(
            self, text=_format_time(entry.timestamp),
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
            width=72,
        ).grid(row=0, column=0, padx=(0, S_3), pady=S_2, sticky="w")

    def _col_filename(self, entry: HistoryEntry):
        ctk.CTkLabel(
            self, text=_truncate(entry.input_filename),
            font=font(FS_BODY, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).grid(row=0, column=1, padx=(0, S_3), pady=S_2, sticky="ew")

    def _col_mode(self, entry: HistoryEntry):
        text_color, bg_color, label = _MODE_MAP.get(
            entry.mode, (FG_MUTED, BORDER_LIGHT, entry.mode),
        )
        tag = ctk.CTkFrame(self, fg_color=bg_color, corner_radius=4)
        tag.grid(row=0, column=2, padx=(0, S_3), pady=S_2, sticky="w")
        ctk.CTkLabel(
            tag, text=label,
            font=font(11, "bold"),
            text_color=text_color,
        ).pack(padx=8, pady=2)

    def _col_codebook(self, entry: HistoryEntry):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=0, column=3, padx=(0, S_3), pady=S_2, sticky="w")
        ctk.CTkLabel(
            box, text=_truncate(entry.codebook_name or "-", 18),
            font=font(FS_LABEL),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            box, text=entry.codebook_version or "",
            font=font(11),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w")

    def _col_replacements(self, entry: HistoryEntry):
        if entry.status == "done" and entry.replacements:
            text = str(entry.replacements)
        else:
            text = "--"
        ctk.CTkLabel(
            self, text=text,
            font=font(FS_LABEL),
            text_color=FG_MUTED, anchor="center",
            width=40,
        ).grid(row=0, column=4, padx=(0, S_3), pady=S_2)

    def _col_status(self, entry: HistoryEntry):
        text_color, bg_color, text = _STATUS_MAP.get(
            entry.status, (FG_MUTED, BORDER_LIGHT, entry.status),
        )
        badge = ctk.CTkFrame(self, fg_color=bg_color, corner_radius=RADIUS_PILL)
        badge.grid(row=0, column=5, padx=(0, S_3), pady=S_2, sticky="w")

        # 状态圆点
        ctk.CTkFrame(
            badge, fg_color=text_color,
            width=6, height=6, corner_radius=3,
        ).pack(side="left", padx=(8, 4), pady=6)

        ctk.CTkLabel(
            badge, text=text,
            font=font(11, "bold"),
            text_color=text_color,
        ).pack(side="left", padx=(0, 8))

    def _col_action(self, entry: HistoryEntry):
        if entry.status == "done" and entry.output_path:
            ctk.CTkButton(
                self, text="打开目录",
                font=font(FS_SMALL),
                width=64, height=24,
                corner_radius=RADIUS_BTN,
                fg_color="transparent", text_color=PRIMARY,
                hover_color=_HOVER_BG,
                command=self._open_dir,
            ).grid(row=0, column=6, padx=(0, S_2), pady=S_2)
        elif entry.status in ("failed", "conflict"):
            ctk.CTkButton(
                self, text="详情",
                font=font(FS_SMALL),
                width=48, height=24,
                corner_radius=RADIUS_BTN,
                fg_color="transparent", text_color=FG_MUTED,
                hover_color=_HOVER_BG,
                command=self._show_detail,
            ).grid(row=0, column=6, padx=(0, S_2), pady=S_2)
        else:
            ctk.CTkLabel(
                self, text="--",
                font=font(FS_SMALL),
                text_color=FG_SUBTLE, width=48,
            ).grid(row=0, column=6, padx=(0, S_2), pady=S_2)

    # -------------------- 行为 --------------------

    def _hover(self, active: bool):
        self.configure(fg_color=_HOVER_BG if active else "transparent")

    def _open_dir(self):
        """在系统文件管理器中打开输出文件所在目录。"""
        path = self._entry.output_path
        dirname = os.path.dirname(path) if path else ""
        if not dirname:
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", dirname])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", dirname])
        else:
            subprocess.Popen(["xdg-open", dirname])

    def _show_detail(self):
        if self._on_detail:
            self._on_detail(self._entry)
