"""密码本页面：完整实现，严格对照 codebook.html 设计页面

模块结构（自上而下）：
1. 页头：标题 + 副标题 + 右上角"选择密码本文件"按钮
2. 当前密码本卡片：文件图标+文件名+badge+路径+元信息+3个操作按钮
3. 统计卡片：3列网格，左边框颜色区分（teal/amber/amber）
4. 校验结果卡片：标题+副标题+校验项列表（dot+文字+分隔线）
5. 安全提示卡片：info 左边框+图标+标题+描述
6. 密码本格式指南：可折叠区域，含 code-block 样式
"""
import os
import subprocess
import sys
from tkinter import filedialog

import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_TITLE, FS_SECTION, FS_BODY, FS_LABEL, FS_SMALL,
    FW_MEDIUM,
    S_2, S_3, S_4, S_5, S_6,
    RADIUS_CARD, RADIUS_BTN, RADIUS_PILL, RADIUS_INPUT,
    BG_PAGE, BG_CARD, BORDER, BORDER_LIGHT,
    FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, WARNING, ERROR, INFO,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
    BTN_HEIGHT, BTN_HEIGHT_SM, MAX_WIDTH_CODEBOOK,
)
from docmask.ui.state import AppState
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.scroll_frame import PageScrollFrame


class CodebookPage(ctk.CTkFrame):
    """密码本页面 — 完整实现"""

    def __init__(self, master, state: AppState, controller, on_navigate: callable = None, **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate
        self._guide_expanded = False

        self._build()

    def _build(self):
        # 滚动容器
        self._scroll = PageScrollFrame(
            self, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=FG_SUBTLE,
        )
        self._scroll.pack(fill="both", expand=True)

        # 内容容器跟随滚动视口宽度，避免 Configure 回调造成布局反馈循环。
        self._content = ctk.CTkFrame(self._scroll.content, fg_color="transparent")
        self._content.pack(fill="x", padx=S_6, pady=S_6)

        for name, builder in (
            ("header", self._build_header),
            ("codebook-card", self._build_codebook_card),
            ("stats", self._build_stats),
            ("validation", self._build_validation),
            ("safety-tip", self._build_safety_tip),
            ("guide", self._build_guide),
        ):
            builder()

    # ======================== 页头 ========================

    def _build_header(self):
        header = ctk.CTkFrame(self._content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_5))

        # 左侧：标题 + 副标题
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")

        ctk.CTkLabel(
            left, text="密码本",
            font=font(20, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            left, text="校验规则完整性，提前发现不可逆风险",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 右侧：选择密码本按钮
        self._select_btn = ctk.CTkButton(
            header, text="选择密码本文件",
            font=font(FS_BODY, FW_MEDIUM),
            height=BTN_HEIGHT,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            image=get_ctk_image("folder-open", 16, PRIMARY_FG),
            compound="left",
            command=self._on_select_codebook,
        )
        self._select_btn.pack(side="right")

    # ======================== 当前密码本卡片 ========================

    def _build_codebook_card(self):
        self._cb_card = self._make_card(self._content)
        self._cb_card.pack(fill="x", pady=(0, S_5))

        self._cb_card_inner = ctk.CTkFrame(self._cb_card, fg_color="transparent")
        self._cb_card_inner.pack(fill="x", padx=S_5, pady=S_5)

    def _render_codebook_card(self):
        for child in self._cb_card_inner.winfo_children():
            child.destroy()

        cb = self.state.codebook

        if not cb.is_loaded:
            # 空状态
            empty = ctk.CTkFrame(self._cb_card_inner, fg_color="transparent")
            empty.pack(fill="x", pady=S_4)

            ctk.CTkLabel(
                empty,
                image=get_ctk_image("file-text", 32, FG_SUBTLE),
                text="",
            ).pack(pady=(0, S_3))

            ctk.CTkLabel(
                empty, text="尚未加载密码本",
                font=font(FS_BODY, FW_MEDIUM),
                text_color=FG_MUTED,
            ).pack()

            ctk.CTkLabel(
                empty, text="点击右上角按钮选择 .txt 密码本文件",
                font=font(FS_SMALL),
                text_color=FG_SUBTLE,
            ).pack(pady=(2, 0))
            return

        # 第一行：文件图标 + 文件名 + badge
        row1 = ctk.CTkFrame(self._cb_card_inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, S_3))

        ctk.CTkLabel(
            row1,
            image=get_ctk_image("file-text", 20, PRIMARY),
            text="",
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkLabel(
            row1,
            text=os.path.basename(cb.path or ""),
            font=font(FS_BODY, "bold"),
            text_color=FG_MAIN,
        ).pack(side="left")

        # badge: 校验通过/失败
        if cb.valid:
            self._make_badge(row1, "check-circle", "校验通过", SUCCESS, BG_SUCCESS)
        else:
            self._make_badge(row1, "alert-triangle", "校验失败", ERROR, BG_ERROR)

        # 第二行：路径
        row2 = ctk.CTkFrame(self._cb_card_inner, fg_color="transparent")
        row2.pack(fill="x", pady=(0, S_3))

        ctk.CTkLabel(
            row2,
            image=get_ctk_image("folder-open", 14, FG_MUTED),
            text="",
        ).pack(side="left", padx=(0, S_2))

        ctk.CTkLabel(
            row2, text=cb.path or "",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(side="left")

        # 第三行：元信息（精确规则 | 正则规则 | 编码 | 校验时间）
        row3 = ctk.CTkFrame(self._cb_card_inner, fg_color="transparent")
        row3.pack(fill="x", pady=(0, S_4))

        meta_items = [
            f"{cb.exact_count} 条精确规则",
            f"{cb.regex_count} 条正则规则",
            "UTF-8",
            "刚刚校验",
        ]
        for i, item in enumerate(meta_items):
            if i > 0:
                # 分隔符
                sep = ctk.CTkFrame(row3, width=1, height=12, fg_color=BORDER, corner_radius=0)
                sep.pack(side="left", padx=S_3)
            ctk.CTkLabel(
                row3, text=item,
                font=font(FS_SMALL),
                text_color=FG_MUTED,
            ).pack(side="left")

        # 第四行：操作按钮
        row4 = ctk.CTkFrame(self._cb_card_inner, fg_color="transparent")
        row4.pack(fill="x")

        ctk.CTkButton(
            row4, text="重新校验",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("refresh", 16, FG_MAIN),
            compound="left",
            command=self._on_revalidate,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            row4, text="在系统中定位",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("folder-search", 16, FG_MAIN),
            compound="left",
            command=self._on_reveal,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            row4, text="更换文件",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("folder-open", 16, FG_MAIN),
            compound="left",
            command=self._on_select_codebook,
        ).pack(side="left")

    # ======================== 统计卡片 ========================

    def _build_stats(self):
        self._stats_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        self._stats_frame.pack(fill="x", pady=(0, S_5))

        # 3列网格
        self._stats_frame.grid_columnconfigure(0, weight=1, uniform="stat")
        self._stats_frame.grid_columnconfigure(1, weight=1, uniform="stat")
        self._stats_frame.grid_columnconfigure(2, weight=1, uniform="stat")

        self._stat_cards = {}
        for i, (key, title, border_color, value_color) in enumerate([
            ("reversible", "可逆规则", PRIMARY, PRIMARY),
            ("regex", "正则规则", WARNING, WARNING),
            ("risk", "风险检查", WARNING, WARNING),
        ]):
            card = self._make_stat_card(self._stats_frame, title, border_color)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else S_3, 0))
            self._stat_cards[key] = (card, value_color)

    def _make_stat_card(self, parent, title, border_color):
        """统计卡片：左边框 3px 颜色"""
        card = ctk.CTkFrame(
            parent, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_4, pady=S_4)

        # 左边框颜色条（通过 border_width 模拟）
        # CustomTkinter 不支持单边边框，用内部色条近似
        border_bar = ctk.CTkFrame(
            card, width=3, corner_radius=0,
            fg_color=border_color,
        )
        border_bar.place(x=0, y=0, relheight=1)

        ctk.CTkLabel(
            inner, text=title,
            font=font(FS_SMALL, FW_MEDIUM),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, S_2))

        value_label = ctk.CTkLabel(
            inner, text="0",
            font=font(22, "bold"),
            text_color=FG_MAIN, anchor="w",
        )
        value_label.pack(anchor="w")

        card._value_label = value_label
        return card

    def _render_stats(self):
        cb = self.state.codebook

        # 可逆规则
        card, color = self._stat_cards["reversible"]
        card._value_label.configure(text=str(cb.exact_count), text_color=color)

        # 正则规则
        card, color = self._stat_cards["regex"]
        card._value_label.configure(text=str(cb.regex_count), text_color=color)

        # 风险检查
        card, color = self._stat_cards["risk"]
        if cb.warning_count > 0:
            card._value_label.configure(text=f"{cb.warning_count} 项警告", text_color=color)
        elif cb.valid:
            card._value_label.configure(text="无风险", text_color=SUCCESS)
        else:
            card._value_label.configure(text=f"{cb.error_count} 项错误", text_color=ERROR)

    # ======================== 校验结果 ========================

    def _build_validation(self):
        self._val_card = self._make_card(self._content)
        self._val_card.pack(fill="x", pady=(0, S_5))

        self._val_inner = ctk.CTkFrame(self._val_card, fg_color="transparent")
        self._val_inner.pack(fill="x", padx=S_5, pady=S_5)

    def _render_validation(self):
        for child in self._val_inner.winfo_children():
            child.destroy()

        # 标题
        ctk.CTkLabel(
            self._val_inner, text="校验结果",
            font=font(FS_SECTION, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            self._val_inner, text="规则完整性分析",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w", pady=(2, S_4))

        cb = self.state.codebook

        if not cb.is_loaded:
            ctk.CTkLabel(
                self._val_inner, text="请先加载密码本",
                font=font(FS_BODY),
                text_color=FG_SUBTLE,
            ).pack(pady=S_4)
            return

        # 校验项列表
        items = []
        if cb.is_loaded:
            # 解析 messages
            has_dup = any("重复" in m for m in cb.messages)
            has_cross = any("交叉冲突" in m for m in cb.messages)
            has_regex_err = any(m.startswith("ERROR") and "正则" in m for m in cb.messages)
            has_regex_warn = cb.has_regex

            items.append(("success" if not has_dup else "warning",
                         "未发现重复脱敏词" if not has_dup else "发现重复脱敏词"))
            items.append(("success" if not has_cross else "warning",
                         "未发现精确规则交叉冲突" if not has_cross else "发现精确规则交叉冲突"))
            items.append(("success" if not has_regex_err else "warning",
                         "正则表达式格式有效" if not has_regex_err else "正则表达式格式有误"))
            if has_regex_warn:
                items.append(("warning", "包含正则规则，匹配到的原始内容无法恢复"))
            items.append(("info", "文档级脱敏词冲突将在添加待处理文件后检查"))

        for i, (level, text) in enumerate(items):
            row = ctk.CTkFrame(self._val_inner, fg_color="transparent")
            row.pack(fill="x", pady=(0 if i == 0 else 0, 0))

            # dot
            dot_colors = {
                "success": SUCCESS,
                "warning": WARNING,
                "info": INFO,
            }
            dot_color = dot_colors.get(level, FG_MUTED)

            dot = ctk.CTkFrame(row, width=8, height=8, corner_radius=4, fg_color=dot_color)
            dot.grid_propagate(False)
            dot.pack(side="left", padx=(0, S_3), pady=(S_2, 0), anchor="n")

            ctk.CTkLabel(
                row, text=text,
                font=font(FS_BODY),
                text_color=FG_MAIN if level != "info" else FG_MUTED,
                anchor="w", justify="left",
            ).pack(side="left", fill="x", expand=True)

            # 分隔线
            if i < len(items) - 1:
                ctk.CTkFrame(
                    self._val_inner, height=1, fg_color=BORDER, corner_radius=0,
                ).pack(fill="x", pady=S_3)

    # ======================== 安全提示 ========================

    def _build_safety_tip(self):
        card = ctk.CTkFrame(
            self._content, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=INFO, border_width=1,
        )
        card.pack(fill="x", pady=(0, S_5))

        # 左边框颜色条
        border_bar = ctk.CTkFrame(
            card, width=3, corner_radius=0,
            fg_color=INFO,
        )
        border_bar.place(x=0, y=0, relheight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_5)

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkLabel(
            row,
            image=get_ctk_image("info", 20, INFO),
            text="",
        ).pack(side="left", padx=(0, S_3), anchor="n")

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            text_frame, text="安全提示",
            font=font(FS_BODY, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w", pady=(0, S_2))

        ctk.CTkLabel(
            text_frame,
            text="密码本包含原文与脱敏词的对应关系，请妥善保管。DocMask 不上传文件。",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w", justify="left",
        ).pack(anchor="w")

    # ======================== 密码本格式指南 ========================

    def _build_guide(self):
        self._guide_card = self._make_card(self._content)
        self._guide_card.pack(fill="x", pady=(0, S_5))

        self._guide_inner = ctk.CTkFrame(self._guide_card, fg_color="transparent")
        self._guide_inner.pack(fill="x", padx=S_5, pady=S_5)

        # 折叠标题
        self._guide_header = ctk.CTkFrame(self._guide_inner, fg_color="transparent")
        self._guide_header.pack(fill="x")

        self._guide_toggle = ctk.CTkButton(
            self._guide_header, text="密码本格式指南",
            font=font(FS_BODY, FW_MEDIUM),
            height=36,
            corner_radius=RADIUS_BTN,
            fg_color="transparent",
            text_color=PRIMARY,
            hover_color=BG_PAGE,
            image=get_ctk_image("book-open", 16, PRIMARY),
            compound="left",
            anchor="w",
            command=self._toggle_guide,
        )
        self._guide_toggle.pack(fill="x")

        # 展开内容（默认隐藏）
        self._guide_body = ctk.CTkFrame(self._guide_inner, fg_color="transparent")
        # 不 pack，默认隐藏

    def _toggle_guide(self):
        self._guide_expanded = not self._guide_expanded
        if self._guide_expanded:
            self._guide_body.pack(fill="x", pady=(S_3, 0))
            self._render_guide_body()
        else:
            self._guide_body.pack_forget()

    def _render_guide_body(self):
        for child in self._guide_body.winfo_children():
            child.destroy()

        sections = [
            ("精确匹配格式", "原文==>脱敏词",
             "每行一条规则，使用 ==> 分隔原文和脱敏后的替换词。", None),
            ("正则匹配格式", "/正则表达式/==>脱敏词",
             "正则规则匹配到的原始内容 不可恢复，请谨慎使用。", WARNING),
            ("占位符建议", "⟦DM-NAME-01⟧",
             "使用不易自然出现的专用标记作为脱敏词。", None),
            ("注意事项", "%、!、￥ 等常见符号",
             "不建议使用常见单字符符号作为数字替换值。", WARNING),
        ]

        for title, code, desc, desc_color in sections:
            section = ctk.CTkFrame(self._guide_body, fg_color="transparent")
            section.pack(fill="x", pady=(0, S_4))

            ctk.CTkLabel(
                section, text=title,
                font=font(FS_BODY, FW_MEDIUM),
                text_color=WARNING if desc_color == WARNING else FG_MAIN,
                anchor="w",
            ).pack(anchor="w", pady=(0, S_2))

            # code-block 样式
            code_block = ctk.CTkFrame(
                section, fg_color=BG_PAGE,
                corner_radius=RADIUS_INPUT,
                border_color=BORDER, border_width=1,
            )
            code_block.pack(fill="x", pady=(0, S_2))

            ctk.CTkLabel(
                code_block, text=code,
                font=("Cascadia Code", FS_SMALL),
                text_color=FG_MAIN, anchor="w",
            ).pack(fill="x", padx=S_4, pady=S_3)

            ctk.CTkLabel(
                section, text=desc,
                font=font(FS_SMALL),
                text_color=desc_color or FG_MUTED,
                anchor="w", justify="left",
            ).pack(anchor="w")

    # ======================== 辅助方法 ========================

    def _make_card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER,
            border_width=1,
        )

    def _make_badge(self, parent, icon_name, text, text_color, bg_color):
        """创建 badge pill"""
        badge = ctk.CTkFrame(
            parent, fg_color=bg_color,
            corner_radius=RADIUS_PILL,
        )
        badge.pack(side="left", padx=S_3)

        ctk.CTkLabel(
            badge,
            image=get_ctk_image(icon_name, 14, text_color),
            text="",
        ).pack(side="left", padx=(10, 4))

        ctk.CTkLabel(
            badge, text=text,
            font=font(FS_SMALL, FW_MEDIUM),
            text_color=text_color,
        ).pack(side="left", padx=(0, 10))

    # ======================== 事件处理 ========================

    def _on_select_codebook(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            cb_state = self.controller.load_codebook(path)
            self.state.codebook = cb_state
            self.on_show()

    def _on_revalidate(self):
        if self.state.codebook.path:
            cb_state = self.controller.load_codebook(self.state.codebook.path)
            self.state.codebook = cb_state
            self.on_show()

    def _on_reveal(self):
        path = self.state.codebook.path
        if not path:
            return
        dirname = os.path.dirname(path) or "."
        if sys.platform == "darwin":
            subprocess.Popen(["open", dirname])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", dirname])

    # ======================== 刷新 ========================

    def on_show(self):
        """页面被显示时刷新"""
        self._render_codebook_card()
        self._render_stats()
        self._render_validation()
