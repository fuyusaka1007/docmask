"""路径选择器：输入框 + 浏览按钮"""
from __future__ import annotations

import os
import customtkinter as ctk
from tkinter import filedialog

from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.theme import (
    font, FS_BODY, S_2, S_3, BTN_HEIGHT_SM, INPUT_HEIGHT, RADIUS_BTN, RADIUS_INPUT,
    BORDER, BG_CARD, BG_PAGE, FG_MAIN, FG_MUTED, PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
)


class PathPicker(ctk.CTkFrame):
    """路径输入 + 浏览按钮"""

    def __init__(
        self,
        master,
        placeholder: str = "请选择文件...",
        button_text: str = "浏览",
        file_mode: bool = True,  # True=选文件, False=选目录
        filetypes: list | None = None,
        on_change: callable = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._file_mode = file_mode
        self._filetypes = filetypes or [("文本文件", "*.txt"), ("所有文件", "*.*")]
        self._on_change = on_change

        self._entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            font=font(FS_BODY),
            height=INPUT_HEIGHT,
            corner_radius=RADIUS_INPUT,
            border_color=BORDER,
            fg_color=BG_CARD,
            text_color=FG_MAIN,
        )
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, S_3))
        self._entry.bind("<KeyRelease>", self._on_keyrelease)

        self._btn = ctk.CTkButton(
            self,
            text=button_text,
            font=font(FS_BODY),
            width=80,
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            command=self._on_browse,
            fg_color=BG_CARD,
            hover_color=BG_PAGE,
            text_color=FG_MAIN,
            border_color=BORDER,
            border_width=1,
            image=get_ctk_image("folder-open", 16, FG_MAIN),
            compound="left",
        )
        self._btn.pack(side="right")

    def _on_browse(self):
        if self._file_mode:
            path = filedialog.askopenfilename(filetypes=self._filetypes)
        else:
            path = filedialog.askdirectory()

        if path:
            self._entry.delete(0, "end")
            self._entry.insert(0, path)
            if self._on_change:
                self._on_change(path)

    def _on_keyrelease(self, event):
        if self._on_change:
            self._on_change(self._entry.get())

    def get_path(self) -> str:
        return self._entry.get().strip()

    def set_path(self, path: str) -> None:
        self._entry.delete(0, "end")
        self._entry.insert(0, path)

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._entry.configure(state=state)
        self._btn.configure(state=state)
