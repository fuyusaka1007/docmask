"""设置与帮助页面：完整实现，严格对照 settings.html 设计页面

模块结构（4个卡片）：
1. 外观：主题 + 界面缩放
2. 处理默认值：默认格式 + 默认输出位置 + 覆盖率报告
3. 日志与隐私：日志级别 + 打开日志 + 清空日志
4. 帮助：按钮组 + info 说明
"""
import os
import subprocess
import sys
import logging
from tkinter import messagebox

import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_SECTION, FS_BODY, FS_LABEL, FS_SMALL,
    S_2, S_3, S_4, S_5, S_6,
    RADIUS_CARD, RADIUS_BTN, RADIUS_INPUT,
    BG_PAGE, BG_CARD, BORDER,
    FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, INFO,
    BTN_HEIGHT, BTN_HEIGHT_SM, MAX_WIDTH_SETTINGS,
)
from docmask.ui.state import AppState
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.scroll_frame import PageScrollFrame
from docmask import __version__


class SettingsPage(ctk.CTkFrame):
    """设置与帮助页面 — 完整实现"""

    def __init__(self, master, state: AppState, controller,
                 on_navigate: callable = None,
                 on_settings_change: callable = None,
                 **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate
        self.on_settings_change = on_settings_change

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

        self._build_header()
        self._build_appearance_card()
        self._build_defaults_card()
        self._build_logging_card()
        self._build_help_card()

    # ======================== 页头 ========================

    def _build_header(self):
        header = ctk.CTkFrame(self._content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_5))

        ctk.CTkLabel(
            header, text="设置与帮助",
            font=font(20, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            header, text="自定义 DocMask 的处理方式",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    # ======================== 外观卡片 ========================

    def _build_appearance_card(self):
        card = self._make_card(self._content)
        card.pack(fill="x", pady=(0, S_5))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_5)

        self._section_label(inner, "外观")

        # 主题选择
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(S_4, 0))

        self._row_label(row1, "主题")
        self._theme_menu = ctk.CTkOptionMenu(
            row1,
            values=["深色", "浅色", "跟随系统"],
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_INPUT,
            fg_color=BG_PAGE, button_color=BORDER,
            button_hover_color=FG_SUBTLE,
            text_color=FG_MAIN,
            font=font(FS_BODY),
            dropdown_font=font(FS_BODY),
            command=self._on_theme_change,
        )
        self._theme_menu.set(self.state.settings.theme)
        self._theme_menu.pack(side="right")

        # 分隔线
        self._separator(inner)

        # 界面缩放
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 0))

        self._row_label(row2, "界面缩放")
        self._scale_menu = ctk.CTkOptionMenu(
            row2,
            values=["100%", "110%", "125%", "150%"],
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_INPUT,
            fg_color=BG_PAGE, button_color=BORDER,
            button_hover_color=FG_SUBTLE,
            text_color=FG_MAIN,
            font=font(FS_BODY),
            dropdown_font=font(FS_BODY),
            command=self._on_scale_change,
        )
        self._scale_menu.set(self.state.settings.scale)
        self._scale_menu.pack(side="right")

    # ======================== 处理默认值卡片 ========================

    def _build_defaults_card(self):
        card = self._make_card(self._content)
        card.pack(fill="x", pady=(0, S_5))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_5)

        self._section_label(inner, "处理默认值")

        # 默认格式 checkbox 组
        fmt_frame = ctk.CTkFrame(inner, fg_color="transparent")
        fmt_frame.pack(fill="x", pady=(S_4, 0))

        self._row_label(fmt_frame, "默认格式")

        fmt_btns = ctk.CTkFrame(fmt_frame, fg_color="transparent")
        fmt_btns.pack(side="right")

        self._fmt_vars = {}
        for fmt in ["docx", "doc", "txt"]:
            var = ctk.StringVar(value="1" if fmt in self.state.format_filters else "0")
            self._fmt_vars[fmt] = var
            cb = ctk.CTkCheckBox(
                fmt_btns, text=fmt.upper(),
                font=font(FS_BODY),
                variable=var, onvalue="1", offvalue="0",
                height=BTN_HEIGHT_SM,
                checkbox_width=20, checkbox_height=20,
                corner_radius=4,
                fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
                text_color=FG_MAIN,
                command=lambda f=fmt: self._on_format_change(f),
            )
            cb.pack(side="left", padx=(0, S_4))

        # 分隔线
        self._separator(inner)

        # 默认输出位置 radio
        out_frame = ctk.CTkFrame(inner, fg_color="transparent")
        out_frame.pack(fill="x", pady=(0, 0))

        self._row_label(out_frame, "默认输出位置")

        out_btns = ctk.CTkFrame(out_frame, fg_color="transparent")
        out_btns.pack(side="right")

        self._output_var = ctk.StringVar(
            value="same" if self.state.output_same_dir else "custom"
        )

        rb1 = ctk.CTkRadioButton(
            out_btns, text="原目录",
            font=font(FS_BODY),
            variable=self._output_var, value="same",
            height=BTN_HEIGHT_SM,
            radiobutton_width=20, radiobutton_height=20,
            corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
            text_color=FG_MAIN,
            command=self._on_output_change,
        )
        rb1.pack(side="left", padx=(0, S_4))

        rb2 = ctk.CTkRadioButton(
            out_btns, text="指定目录",
            font=font(FS_BODY),
            variable=self._output_var, value="custom",
            height=BTN_HEIGHT_SM,
            radiobutton_width=20, radiobutton_height=20,
            corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
            text_color=FG_MAIN,
            command=self._on_output_change,
        )
        rb2.pack(side="left")

        # 分隔线
        self._separator(inner)

        # 覆盖率报告 checkbox
        report_frame = ctk.CTkFrame(inner, fg_color="transparent")
        report_frame.pack(fill="x", pady=(0, 0))

        self._row_label(report_frame, "覆盖率报告")

        self._report_var = ctk.StringVar(
            value="1" if self.state.generate_report else "0"
        )
        cb = ctk.CTkCheckBox(
            report_frame, text="脱敏后生成覆盖率报告",
            font=font(FS_BODY),
            variable=self._report_var, onvalue="1", offvalue="0",
            height=BTN_HEIGHT_SM,
            checkbox_width=20, checkbox_height=20,
            corner_radius=4,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
            text_color=FG_MAIN,
            command=self._on_report_change,
        )
        cb.pack(side="right")

    # ======================== 日志与隐私卡片 ========================

    def _build_logging_card(self):
        card = self._make_card(self._content)
        card.pack(fill="x", pady=(0, S_5))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_5)

        self._section_label(inner, "日志与隐私")

        # 日志级别
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(S_4, 0))

        self._row_label(row1, "日志级别")
        self._log_menu = ctk.CTkOptionMenu(
            row1,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_INPUT,
            fg_color=BG_PAGE, button_color=BORDER,
            button_hover_color=FG_SUBTLE,
            text_color=FG_MAIN,
            font=font(FS_BODY),
            dropdown_font=font(FS_BODY),
            command=self._on_log_level_change,
        )
        self._log_menu.set(self.state.settings.log_level)
        self._log_menu.pack(side="right")

        # info 说明
        info_row = ctk.CTkFrame(inner, fg_color="transparent")
        info_row.pack(fill="x", pady=(S_3, 0))

        ctk.CTkLabel(
            info_row,
            image=get_ctk_image("info", 14, FG_MUTED),
            text="",
        ).pack(side="left", padx=(0, S_2), anchor="center")

        ctk.CTkLabel(
            info_row,
            text="日志仅保存在本地，不会上传任何信息。",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w", justify="left",
        ).pack(side="left", fill="x", expand=True)

        # 分隔线
        self._separator(inner)

        # 按钮组
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 0))

        ctk.CTkButton(
            btn_row, text="打开日志文件",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("file-text", 16, FG_MAIN),
            compound="left",
            command=self._on_open_log_file,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            btn_row, text="打开日志目录",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("folder-open", 16, FG_MAIN),
            compound="left",
            command=self._on_open_log_dir,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            btn_row, text="清空日志",
            font=font(FS_LABEL),
            height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("trash", 16, FG_MAIN),
            compound="left",
            command=self._on_clear_log,
        ).pack(side="left")

        # 分隔线
        self._separator(inner)

        # 记录工作历史开关
        history_row = ctk.CTkFrame(inner, fg_color="transparent")
        history_row.pack(fill="x", pady=(0, 0))

        self._history_var = ctk.StringVar(
            value="1" if self.state.history_enabled else "0"
        )
        ctk.CTkCheckBox(
            history_row, text="记录工作历史",
            font=font(FS_BODY),
            variable=self._history_var, onvalue="1", offvalue="0",
            height=BTN_HEIGHT_SM,
            checkbox_width=20, checkbox_height=20,
            corner_radius=4,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
            text_color=FG_MAIN,
            command=self._on_history_change,
        ).pack(side="left")

        # info 说明
        history_info = ctk.CTkFrame(history_row, fg_color="transparent")
        history_info.pack(side="left", padx=(S_3, 0))
        ctk.CTkLabel(
            history_info,
            image=get_ctk_image("info", 14, FG_MUTED),
            text="",
        ).pack(side="left", padx=(0, S_2), anchor="center")
        ctk.CTkLabel(
            history_info,
            text="记录脱敏/恢复操作的文件和密码本信息，仅保存在本地",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w", justify="left",
        ).pack(side="left", fill="x", expand=True)

    # ======================== 帮助卡片 ========================

    def _build_help_card(self):
        card = self._make_card(self._content)
        card.pack(fill="x", pady=(0, S_5))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_5)

        self._section_label(inner, "帮助")

        # 按钮组（2x2 grid）
        btn_grid = ctk.CTkFrame(inner, fg_color="transparent")
        btn_grid.pack(fill="x", pady=(S_4, 0))
        btn_grid.grid_columnconfigure(0, weight=1, uniform="help")
        btn_grid.grid_columnconfigure(1, weight=1, uniform="help")

        help_items = [
            ("book-open", "密码本编写指南"),
            ("help-circle", "常见问题"),
            ("file-text", "支持的文档范围"),
            ("info", "关于 DocMask"),
        ]

        for i, (icon_name, label) in enumerate(help_items):
            row, col = divmod(i, 2)
            btn = ctk.CTkButton(
                btn_grid, text=label,
                font=font(FS_BODY),
                height=BTN_HEIGHT,
                corner_radius=RADIUS_BTN,
                fg_color=BG_PAGE, text_color=FG_MAIN,
                border_color=BORDER, border_width=1,
                hover_color=BG_CARD,
                image=get_ctk_image(icon_name, 18, FG_MAIN),
                compound="left",
                anchor="w",
                command=lambda l=label: self._on_help_click(l),
            )
            btn.grid(
                row=row, column=col, sticky="ew",
                padx=(0 if col == 0 else S_3, 0 if col == 1 else S_3),
                pady=(0 if row == 0 else S_3, 0),
            )

        # info 说明
        info_row = ctk.CTkFrame(inner, fg_color="transparent")
        info_row.pack(fill="x", pady=(S_4, 0))

        ctk.CTkLabel(
            info_row,
            image=get_ctk_image("info", 14, FG_MUTED),
            text="",
        ).pack(side="left", padx=(0, S_2), anchor="center")

        ctk.CTkLabel(
            info_row,
            text="DocMask 是纯本地运行的文档脱敏工具，不会上传任何文件。",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w", justify="left",
        ).pack(side="left", fill="x", expand=True)

    # ======================== 辅助方法 ========================

    def _make_card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER,
            border_width=1,
        )

    def _section_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            font=font(FS_SECTION, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(anchor="w")

    def _row_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            font=font(FS_BODY),
            text_color=FG_MAIN,
            height=BTN_HEIGHT_SM,
            anchor="w",
        ).pack(side="left")

    def _separator(self, parent):
        ctk.CTkFrame(
            parent, height=1, fg_color=BORDER, corner_radius=0,
        ).pack(fill="x", pady=S_4)

    # ======================== 事件处理 ========================

    def _save_and_notify(self):
        """同步运行时状态到设置，持久化，并通知其他页面。"""
        self.state.settings.sync_from_state(self.state)
        self.state.settings.save()
        if self.on_settings_change:
            self.on_settings_change(self.state.settings)

    def _on_theme_change(self, value: str):
        self.state.settings.theme = value
        mapping = {"深色": "Dark", "浅色": "Light", "跟随系统": "System"}
        ctk.set_appearance_mode(mapping.get(value, "System"))
        self.state.settings.save()
        if self.on_settings_change:
            self.on_settings_change(self.state.settings)

    def _on_scale_change(self, value: str):
        self.state.settings.scale = value
        scale = int(value.replace("%", "")) / 100.0
        ctk.set_widget_scaling(scale)
        self.state.settings.save()
        if self.on_settings_change:
            self.on_settings_change(self.state.settings)

    def _on_format_change(self, fmt: str):
        if self._fmt_vars[fmt].get() == "1":
            self.state.format_filters.add(fmt)
        else:
            self.state.format_filters.discard(fmt)
        self._save_and_notify()

    def _on_output_change(self):
        self.state.output_same_dir = self._output_var.get() == "same"
        self._save_and_notify()

    def _on_report_change(self):
        self.state.generate_report = self._report_var.get() == "1"
        self._save_and_notify()

    def _on_history_change(self):
        self.state.history_enabled = self._history_var.get() == "1"
        self._save_and_notify()

    def _on_log_level_change(self, value: str):
        self.state.settings.log_level = value
        level = getattr(logging, value, logging.INFO)
        logging.getLogger().setLevel(level)
        self.state.settings.save()

    def _on_open_log_file(self):
        from docmask import config
        log_file = getattr(config, "LOG_FILE", None)
        if log_file and os.path.exists(log_file):
            if sys.platform == "win32":
                os.startfile(log_file)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", log_file])
            else:
                subprocess.Popen(["xdg-open", log_file])

    def _on_open_log_dir(self):
        from docmask import config
        log_file = getattr(config, "LOG_FILE", None)
        if log_file:
            log_dir = os.path.dirname(log_file) or "."
        else:
            log_dir = os.path.expanduser("~/.docmask/logs")
        if sys.platform == "win32":
            subprocess.Popen(["explorer", log_dir])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", log_dir])
        else:
            subprocess.Popen(["xdg-open", log_dir])

    def _on_clear_log(self):
        from docmask import config
        log_file = getattr(config, "LOG_FILE", None)
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, "w") as f:
                    f.truncate(0)
            except Exception:
                pass

    def _on_help_click(self, label: str):
        """帮助按钮点击：弹出说明对话框。"""
        if label == "密码本编写指南":
            messagebox.showinfo(
                "密码本编写指南",
                "密码本格式（.txt 纯文本）：\n\n"
                "1. 精确规则（可逆）：\n"
                "   原文==>替换值\n"
                "   示例：张三==>李四\n\n"
                "2. 正则规则（不可逆）：\n"
                "   regex:正则表达式==>替换值\n"
                "   示例：regex:\\d{11}==>PHONE\n\n"
                "3. 注释行以 # 开头\n\n"
                "4. 同一原文不可重复定义\n"
                "5. 所有替换值必须全局唯一\n"
                "6. 正则不可匹配空字符串",
                parent=self,
            )
        elif label == "常见问题":
            messagebox.showinfo(
                "常见问题",
                "Q: 脱敏后如何恢复？\n"
                "A: 使用同一密码本，选择「恢复文档」模式即可。精确规则可逆，正则规则不可逆。\n\n"
                "Q: 支持 .doc 格式吗？\n"
                "A: 支持，但需要安装 LibreOffice（macOS/Linux）或 Microsoft Word（Windows）进行转换。\n\n"
                "Q: 文件会被上传吗？\n"
                "A: 不会。DocMask 是纯本地工具，所有处理在本地完成。\n\n"
                "Q: 正则规则为什么不可逆？\n"
                "A: 正则匹配的原文不固定，无法建立一一映射关系，因此无法恢复。",
                parent=self,
            )
        elif label == "支持的文档范围":
            messagebox.showinfo(
                "支持的文档范围",
                "支持的输入格式：\n"
                "  • TXT（自动检测编码，输出 UTF-8）\n"
                "  • DOCX（正文、表格、页眉页脚、超链接、脚注尾注、批注）\n"
                "  • DOC（通过 Word/LibreOffice 转换为 DOCX 后处理）\n\n"
                "输出格式：\n"
                "  • TXT → TXT（UTF-8）\n"
                "  • DOCX → DOCX\n"
                "  • DOC → DOCX（格式升级）\n\n"
                "注意：批注回复、修订记录、SmartArt、图表内文本等为有限支持或不支持。",
                parent=self,
            )
        elif label == "关于 DocMask":
            messagebox.showinfo(
                "关于 DocMask",
                f"DocMask v{__version__}\n\n"
                "纯本地运行的文档脱敏工具\n"
                "支持精确规则（可逆）和正则规则（不可逆）\n\n"
                "所有文件处理在本地完成，不会上传任何信息。\n"
                "日志仅记录操作元数据，不记录文档内容。",
                parent=self,
            )

    # ======================== 刷新 ========================

    def on_show(self):
        """页面被显示时同步当前状态。"""
        # 同步主题和缩放
        self._theme_menu.set(self.state.settings.theme)
        self._scale_menu.set(self.state.settings.scale)
        self._log_menu.set(self.state.settings.log_level)

        # 同步格式过滤器
        for fmt, var in self._fmt_vars.items():
            var.set("1" if fmt in self.state.format_filters else "0")

        # 同步输出模式
        self._output_var.set("same" if self.state.output_same_dir else "custom")

        # 同步覆盖率报告
        self._report_var.set("1" if self.state.generate_report else "0")

        # 同步历史记录开关
        self._history_var.set("1" if self.state.history_enabled else "0")
