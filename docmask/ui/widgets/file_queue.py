"""文件队列组件：表格式文件列表"""
import re

import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_BODY, FS_SMALL, FS_LABEL, S_2, S_3, S_4, ROW_HEIGHT,
    RADIUS_BTN, BG_CARD, BORDER, BORDER_LIGHT, FG_MAIN, FG_MUTED,
    FG_SUBTLE, PRIMARY, ERROR, TAG_DOCX, TAG_DOC, TAG_TXT,
    BG_TAG_DOCX, BG_TAG_DOC, BG_TAG_TXT,
)
from docmask.ui.state import FileItem, FileStatus
from docmask.ui.widgets.status_badge import StatusBadge
from docmask.ui.widgets.icon import get_ctk_image

_FMT_TAG = {
    "docx": (TAG_DOCX, BG_TAG_DOCX),
    "doc": (TAG_DOC, BG_TAG_DOC),
    "txt": (TAG_TXT, BG_TAG_TXT),
}


def _parse_dnd_files(data: str) -> list[str]:
    """解析 tkdnd 拖放数据为文件路径列表。

    Windows 路径用 {} 包裹；macOS/Linux 以换行分隔。
    """
    matches = re.findall(r"\{([^}]*)\}", data)
    if matches:
        return [m for m in matches if m]
    return [p.strip() for p in data.split("\n") if p.strip()]


class FileRow(ctk.CTkFrame):
    """单行文件项，使用固定列网格保证上下对齐。"""

    def __init__(self, master, item: FileItem, index: int, on_remove: callable, **kwargs):
        super().__init__(master, fg_color=BG_CARD, corner_radius=0, height=ROW_HEIGHT, **kwargs)
        self.grid_propagate(False)
        self._item = item
        self._index = index
        self._on_remove = on_remove

        self.grid_columnconfigure(0, weight=1, minsize=240)
        self.grid_columnconfigure(1, minsize=90)
        self.grid_columnconfigure(2, minsize=90)
        self.grid_columnconfigure(3, minsize=120)
        self.grid_columnconfigure(4, minsize=70)

        name_text = item.filename if len(item.filename) <= 40 else item.filename[:37] + "..."
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=0, sticky="ew", padx=(S_3, S_2))
        ctk.CTkLabel(
            name_frame, image=get_ctk_image("file-text", 18, PRIMARY), text="", width=20,
        ).pack(side="left", padx=(0, S_2))
        ctk.CTkLabel(
            name_frame, text=name_text, font=font(FS_BODY), text_color=FG_MAIN, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        fg, bg = _FMT_TAG.get(item.fmt, (FG_MUTED, BORDER_LIGHT))
        ctk.CTkLabel(
            self, text=item.fmt.upper(), font=font(FS_SMALL, "bold"),
            text_color=fg, fg_color=bg, corner_radius=10, padx=10, height=20,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            self, text=item.size_str, font=font(FS_SMALL), text_color=FG_MUTED, anchor="w",
        ).grid(row=0, column=2, sticky="w", padx=S_2)

        self._status_badge = StatusBadge(self, status=item.status)
        self._status_badge.grid(row=0, column=3, sticky="w", padx=S_2)

        self._remove_btn = ctk.CTkButton(
            self, text="移除", image=get_ctk_image("trash", 14, ERROR), compound="left",
            font=font(FS_SMALL), width=62, height=28,
            corner_radius=RADIUS_BTN, fg_color="transparent",
            hover_color=("#FCEAEA", "#2B1010"), text_color=ERROR,
            command=self._do_remove,
        )
        self._remove_btn.grid(row=0, column=4, padx=(S_2, S_3))

        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=1, column=0, columnspan=5, sticky="sew",
        )

    def _do_remove(self):
        if self._on_remove:
            self._on_remove(self._index)

    def update_status(self, item: FileItem):
        self._item = item
        self._status_badge.set_status(item.status)
        self._remove_btn.configure(
            state="disabled" if item.status == FileStatus.PROCESSING else "normal"
        )

    def set_removable(self, removable: bool):
        self._remove_btn.configure(state="normal" if removable else "disabled")


class FileQueue(ctk.CTkFrame):
    """文件队列。纵向滚动统一交给工作台页面，不创建嵌套滚动区。"""

    def __init__(
        self,
        master,
        on_remove: callable = None,
        on_add_files: callable = None,
        on_add_folder: callable = None,
        on_clear: callable = None,
        on_drop_files: callable = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_remove = on_remove
        self._on_add_files = on_add_files
        self._on_add_folder = on_add_folder
        self._on_clear = on_clear
        self._on_drop_files = on_drop_files
        self._rows: list[FileRow] = []
        self._dnd_enabled = False
        self._build()
        # 在 UI 构建完成后尝试启用拖放
        self._try_enable_dnd()

    def _build(self):
        self.toolbar = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar.pack(fill="x", pady=(0, S_4))

        ctk.CTkButton(
            self.toolbar, text="添加文件", image=get_ctk_image("plus", 16, FG_MAIN), compound="left", font=font(FS_LABEL), height=36, width=104,
            corner_radius=RADIUS_BTN, fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1, hover_color=("#F4F7FA", "#1E2A38"),
            command=self._do_add_files,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            self.toolbar, text="添加文件夹", image=get_ctk_image("folder-plus", 16, FG_MAIN), compound="left", font=font(FS_LABEL), height=36, width=116,
            corner_radius=RADIUS_BTN, fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1, hover_color=("#F4F7FA", "#1E2A38"),
            command=self._do_add_folder,
        ).pack(side="left")

        self._table = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        self._table.pack(fill="x")

        header = ctk.CTkFrame(self._table, fg_color="transparent", height=36)
        header.pack(fill="x")
        header.pack_propagate(False)
        header.grid_columnconfigure(0, weight=1, minsize=240)
        header.grid_columnconfigure(1, minsize=90)
        header.grid_columnconfigure(2, minsize=90)
        header.grid_columnconfigure(3, minsize=120)
        header.grid_columnconfigure(4, minsize=70)
        for column, text in enumerate(("文件名", "格式", "大小", "状态", "操作")):
            ctk.CTkLabel(
                header, text=text, font=font(FS_SMALL, "bold"),
                text_color=FG_MUTED, anchor="w",
            ).grid(row=0, column=column, sticky="w", padx=S_3 if column == 0 else S_2)
        ctk.CTkFrame(self._table, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x")

        self._rows_frame = ctk.CTkFrame(self._table, fg_color="transparent", corner_radius=0)
        self._rows_frame.pack(fill="x")

        self._empty_frame = ctk.CTkFrame(self._rows_frame, fg_color="transparent", height=150)
        self._empty_frame.pack(fill="x")
        self._empty_frame.pack_propagate(False)
        ctk.CTkLabel(
            self._empty_frame, image=get_ctk_image("file-text", 30, FG_SUBTLE), text="",
        ).pack(pady=(26, 2))
        self._empty_hint = ctk.CTkLabel(
            self._empty_frame, text="拖放文件或文件夹到这里",
            font=font(FS_BODY), text_color=FG_MUTED,
        )
        self._empty_hint.pack()
        ctk.CTkLabel(
            self._empty_frame, text="支持 TXT、DOCX、DOC，可批量处理",
            font=font(FS_SMALL), text_color=FG_SUBTLE,
        ).pack(pady=(2, 0))

        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x", pady=(S_3, 0))
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", pady=(S_3, 0))
        self._count_label = ctk.CTkLabel(
            footer, text="0 个文件", font=font(FS_SMALL), text_color=FG_MUTED, anchor="w",
        )
        self._count_label.pack(side="left")
        self._clear_btn = ctk.CTkButton(
            footer, text="清空", image=get_ctk_image("trash", 16, ERROR), compound="left", font=font(FS_LABEL), height=32, width=58,
            corner_radius=RADIUS_BTN, fg_color="transparent", text_color=ERROR,
            hover_color=("#FCEAEA", "#2B1010"), command=self._do_clear,
        )
        self._clear_btn.pack(side="right")

    def _do_add_files(self):
        if self._on_add_files:
            self._on_add_files()

    def _do_add_folder(self):
        if self._on_add_folder:
            self._on_add_folder()

    def _do_clear(self):
        if self._on_clear:
            self._on_clear()

    def _try_enable_dnd(self):
        """尝试启用拖放支持。需要 tkinterdnd2 且根窗口已初始化 tkdnd。"""
        if not self._on_drop_files:
            return
        root = self.winfo_toplevel()
        if not getattr(root, "dnd_available", False):
            # DnD 不可用：更新提示文案
            self._empty_hint.configure(text="点击上方按钮添加文件或文件夹")
            return
        try:
            self.tk.call("tkdnd::drop_target", "register", self._w, "DND_Files")
            self.bind("<<Drop:DND_Files>>", self._on_dnd_drop)
            self._dnd_enabled = True
        except Exception:
            self._empty_hint.configure(text="点击上方按钮添加文件或文件夹")

    def _on_dnd_drop(self, event):
        """处理拖放文件事件。"""
        if self._on_drop_files:
            paths = _parse_dnd_files(event.data)
            if paths:
                self._on_drop_files(paths)

    def refresh(self, files: list[FileItem], task_running: bool = False):
        for row in self._rows:
            row.destroy()
        self._rows.clear()

        if not files:
            self._empty_frame.pack(fill="x")
            self._count_label.configure(text="0 个文件")
            self._clear_btn.configure(state="disabled")
            return

        self._empty_frame.pack_forget()
        for index, item in enumerate(files):
            row = FileRow(self._rows_frame, item=item, index=index, on_remove=self._handle_remove)
            row.pack(fill="x")
            row.set_removable(not task_running)
            self._rows.append(row)

        self._count_label.configure(text=f"{len(files)} 个文件")
        self._clear_btn.configure(state="disabled" if task_running else "normal")

    def update_row(self, index: int, item: FileItem):
        if 0 <= index < len(self._rows):
            self._rows[index].update_status(item)

    def _handle_remove(self, index: int):
        if self._on_remove:
            self._on_remove(index)

    def set_task_running(self, running: bool):
        for row in self._rows:
            row.set_removable(not running)
        self._clear_btn.configure(state="disabled" if running or not self._rows else "normal")
