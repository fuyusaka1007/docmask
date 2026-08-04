"""弹窗组件：冲突详情、确认对话框"""
import customtkinter as ctk

from docmask.ui.widgets.scroll_frame import PageScrollFrame
from docmask.ui.theme import (
    font, FS_BODY, FS_SECTION, FS_SMALL, S_2, S_3, S_4, S_5,
    BTN_HEIGHT, BTN_HEIGHT_SM, RADIUS_BTN, RADIUS_CARD,
    BG_CARD, BG_PAGE, BORDER, FG_MAIN, FG_MUTED,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG, ERROR, WARNING, SUCCESS, INFO,
    BG_WARNING, BG_ERROR, BG_INFO,
)


class ConfirmDialog(ctk.CTkToplevel):
    """通用确认弹窗

    result: True(确认) / False(取消) / None(关闭)
    """

    def __init__(
        self,
        master,
        title: str = "确认",
        message: str = "",
        confirm_text: str = "确认",
        cancel_text: str = "取消",
        danger: bool = False,
    ):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.result = None
        self._danger = danger

        # 居中
        self.geometry("420x200")
        self.after(10, self._center)

        # 内容
        container = ctk.CTkFrame(self, fg_color=BG_PAGE, corner_radius=0)
        container.pack(fill="both", expand=True)

        # 标题
        ctk.CTkLabel(
            container, text=title,
            font=font(FS_SECTION, "bold"),
            text_color=FG_MAIN,
            anchor="w",
        ).pack(fill="x", padx=S_5, pady=(S_5, S_2))

        # 消息
        ctk.CTkLabel(
            container, text=message,
            font=font(FS_BODY),
            text_color=FG_MUTED,
            anchor="w", justify="left",
            wraplength=360,
        ).pack(fill="x", padx=S_5, pady=(0, S_5))

        # 按钮
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", padx=S_5, pady=(0, S_5), side="bottom")

        ctk.CTkButton(
            btn_frame, text=cancel_text,
            font=font(FS_BODY), height=BTN_HEIGHT_SM, width=80,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=("gray90", "gray25"),
            command=self._on_cancel,
        ).pack(side="right", padx=(S_2, 0))

        confirm_color = ERROR if danger else PRIMARY
        confirm_hover = ("#C03A3A", "#C84A4A") if danger else PRIMARY_HOVER

        ctk.CTkButton(
            btn_frame, text=confirm_text,
            font=font(FS_BODY), height=BTN_HEIGHT_SM, width=80,
            corner_radius=RADIUS_BTN,
            fg_color=confirm_color,
            hover_color=confirm_hover,
            text_color=PRIMARY_FG,
            command=self._on_confirm,
        ).pack(side="right")

        # Esc 取消
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_confirm(self):
        self.result = True
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.result = False
        self.grab_release()
        self.destroy()


class ConflictDialog(ctk.CTkToplevel):
    """冲突详情弹窗

    显示冲突文件的详细信息。
    """

    def __init__(
        self,
        master,
        conflicts: list,  # [(filename, conflict_text), ...]
    ):
        super().__init__(master)
        self.title("发现脱敏词冲突")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        # 计算高度
        height = min(120 + len(conflicts) * 100, 500)
        self.geometry(f"520x{height}")
        self.after(10, self._center)

        # 内容
        container = ctk.CTkFrame(self, fg_color=BG_PAGE, corner_radius=0)
        container.pack(fill="both", expand=True)

        # 标题区
        header = ctk.CTkFrame(container, fg_color=BG_WARNING, corner_radius=RADIUS_CARD)
        header.pack(fill="x", padx=S_5, pady=(S_5, S_3))

        ctk.CTkLabel(
            header, text=f"  !  {len(conflicts)} 个文件无法安全脱敏",
            font=font(FS_SECTION, "bold"),
            text_color=WARNING,
            anchor="w",
        ).pack(fill="x", padx=S_3, pady=S_3)

        # 冲突详情
        detail_frame = PageScrollFrame(
            container, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        detail_frame.pack(fill="both", expand=True, padx=S_5, pady=(0, S_3))

        for filename, conflict_text in conflicts:
            file_frame = ctk.CTkFrame(detail_frame.content, fg_color="transparent")
            file_frame.pack(fill="x", pady=S_2)

            ctk.CTkLabel(
                file_frame, text=filename,
                font=font(FS_BODY, "bold"),
                text_color=FG_MAIN, anchor="w",
            ).pack(fill="x")

            ctk.CTkLabel(
                file_frame, text=conflict_text,
                font=font(FS_SMALL),
                text_color=FG_MUTED, anchor="w", justify="left",
                wraplength=460,
            ).pack(fill="x", pady=(2, 0))

        # 提示
        ctk.CTkLabel(
            container,
            text="继续处理会导致恢复时无法区分原始字符和脱敏结果。\n建议将常见符号替换为专用占位符。",
            font=font(FS_SMALL),
            text_color=FG_MUTED, justify="left",
            wraplength=460,
        ).pack(fill="x", padx=S_5, pady=(0, S_3))

        # 按钮
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", padx=S_5, pady=(0, S_5), side="bottom")

        ctk.CTkButton(
            btn_frame, text="关闭",
            font=font(FS_BODY), height=BTN_HEIGHT_SM, width=80,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            command=self._on_close,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_close(self):
        self.grab_release()
        self.destroy()


def show_confirm(
    master,
    title: str,
    message: str,
    confirm_text: str = "确认",
    cancel_text: str = "取消",
    danger: bool = False,
) -> bool:
    """显示确认弹窗，阻塞直到用户选择"""
    dlg = ConfirmDialog(
        master, title, message,
        confirm_text, cancel_text, danger,
    )
    master.wait_window(dlg)
    return dlg.result or False
