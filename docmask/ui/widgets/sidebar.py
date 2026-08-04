"""侧边导航栏"""
import customtkinter as ctk
from docmask.ui.theme import (
    font, FS_BODY, FS_SMALL, FS_SECTION, S_2, S_3, S_4, S_5,
    NAV_ITEM_HEIGHT, BG_SIDEBAR, FG_SIDEBAR, PRIMARY,
)
from docmask.ui.widgets.icon import get_ctk_image
from docmask import __version__


class Sidebar(ctk.CTkFrame):
    """左侧导航栏"""

    # 导航项: (page_id, 图标, 文字)
    NAV_ITEMS = [
        ("workbench", "workflow", "工作台"),
        ("codebook", "book-open", "密码本"),
        ("results", "clipboard-list", "任务结果"),
        ("settings", "settings", "设置与帮助"),
    ]

    def __init__(self, master, on_navigate: callable, **kwargs):
        super().__init__(
            master,
            width=220,
            corner_radius=0,
            fg_color=BG_SIDEBAR,
            **kwargs,
        )
        self._on_navigate = on_navigate
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._active_page = "workbench"

        self._build_brand()
        self._build_nav()
        self._build_footer()

    def _build_brand(self):
        brand_frame = ctk.CTkFrame(self, fg_color="transparent")
        brand_frame.pack(fill="x", padx=S_5, pady=(S_5, S_4))

        ctk.CTkLabel(
            brand_frame,
            image=get_ctk_image("shield-check", 24, PRIMARY),
            text="",
            width=24,
        ).pack(side="left", padx=(0, S_2))

        text_frame = ctk.CTkFrame(brand_frame, fg_color="transparent")
        text_frame.pack(side="left")

        ctk.CTkLabel(
            text_frame,
            text="DocMask",
            font=font(FS_SECTION, "bold"),
            text_color=("#FFFFFF", "#FFFFFF"),
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            text_frame,
            text="本地文档保护",
            font=font(FS_SMALL),
            text_color=("#667085", "#667085"),
            anchor="w",
        ).pack(anchor="w")

    def _build_nav(self):
        nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        nav_frame.pack(fill="both", expand=True, padx=S_3)

        for page_id, icon, label in self.NAV_ITEMS:
            btn = ctk.CTkButton(
                nav_frame,
                text=label,
                image=get_ctk_image(icon, 20, FG_SIDEBAR),
                compound="left",
                font=font(FS_BODY),
                height=NAV_ITEM_HEIGHT,
                corner_radius=8,
                anchor="w",
                fg_color="transparent",
                hover_color=("#1E2B3D", "#111C2B"),
                text_color=FG_SIDEBAR,
                command=lambda pid=page_id: self._on_click(pid),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[page_id] = btn

        self._update_active()

    def _build_footer(self):
        footer_wrap = ctk.CTkFrame(self, fg_color="transparent")
        footer_wrap.pack(fill="x", side="bottom")
        ctk.CTkFrame(
            footer_wrap, height=1, corner_radius=0, fg_color=("#243143", "#172231"),
        ).pack(fill="x")
        footer = ctk.CTkFrame(footer_wrap, fg_color="transparent")
        footer.pack(fill="x", padx=S_5, pady=S_4)

        footer_line1 = ctk.CTkFrame(footer, fg_color="transparent")
        footer_line1.pack(anchor="w")

        ctk.CTkLabel(
            footer_line1,
            image=get_ctk_image("shield", 14, FG_SIDEBAR),
            text="",
            width=14,
        ).pack(side="left", padx=(0, S_2))

        ctk.CTkLabel(
            footer_line1,
            text="纯本地运行",
            font=font(FS_SMALL),
            text_color=FG_SIDEBAR,
            anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            footer,
            text="文件不会上传",
            font=font(FS_SMALL),
            text_color=("gray50", "gray40"),
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            footer,
            text=f"v{__version__}",
            font=font(FS_SMALL),
            text_color=("gray50", "gray40"),
            anchor="w",
        ).pack(anchor="w", pady=(S_2, 0))

    def _on_click(self, page_id: str):
        self._active_page = page_id
        self._update_active()
        if self._on_navigate:
            self._on_navigate(page_id)

    def _update_active(self):
        for pid, btn in self._nav_buttons.items():
            if pid == self._active_page:
                btn.configure(
                    fg_color=("#112F43", "#0D293B"),
                    text_color=PRIMARY,
                    border_color=PRIMARY,
                    border_width=1,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=FG_SIDEBAR,
                    border_color=BG_SIDEBAR,
                    border_width=1,
                )

    def set_active(self, page_id: str):
        self._active_page = page_id
        self._update_active()
