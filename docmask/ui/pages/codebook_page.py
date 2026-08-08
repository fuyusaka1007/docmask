"""密码本页面：三视图（beta3）

Tab 1 我的密码本：库列表卡片 + 新建/导入/导出/删除/复制
Tab 2 编辑器：规则表格 + 实时校验 + 保存/另存为
Tab 3 版本记录：版本时间线 + 恢复

保留原有的"选择密码本文件"能力（兼容外部文件加载）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from tkinter import filedialog, simpledialog, messagebox

import customtkinter as ctk

from docmask.core.codebook import CodebookRule, REGEX_PREFIX, CODEBOOK_SEPARATOR, COMMENT_PREFIX
from docmask.ui.theme import (
    font, FS_SECTION, FS_BODY, FS_LABEL, FS_SMALL,
    FW_MEDIUM,
    S_2, S_3, S_4, S_5, S_6,
    RADIUS_CARD, RADIUS_BTN, RADIUS_PILL, RADIUS_INPUT, RADIUS_SM,
    BG_PAGE, BG_CARD, BG_INPUT, BORDER, BORDER_LIGHT,
    FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, WARNING, ERROR, INFO,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
    BTN_HEIGHT, BTN_HEIGHT_SM,
)
from docmask.ui.state import AppState
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.scroll_frame import PageScrollFrame
from docmask.ui.widgets.dialogs import show_confirm
from docmask.services.codebook_library import CodebookMeta, VersionInfo


class CodebookPage(ctk.CTkFrame):
    """密码本页面 - 三视图"""

    def __init__(self, master, state: AppState, controller,
                 on_navigate: callable = None, **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate
        self._active_tab = 0  # 0=库列表, 1=编辑器, 2=版本记录
        self._edit_rules: list[CodebookRule] = []
        self._validation_messages: list[str] = []

        self._build()

    # ======================== 主框架 ========================

    def _build(self):
        # 页头
        self._build_header()
        # Tab 栏
        self._build_tab_bar()
        # 三个 Tab 内容容器
        self._tab_frames = []
        for i in range(3):
            f = ctk.CTkFrame(self, fg_color="transparent")
            self._tab_frames.append(f)
        self._build_tab_library()
        self._build_tab_editor()
        self._build_tab_versions()
        self._show_tab(0)

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=S_6, pady=(S_6, S_4))

        ctk.CTkLabel(
            header, text="密码本",
            font=font(20, "bold"),
            text_color=FG_MAIN, anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            header, text="管理密码本、编辑规则、查看版本历史",
            font=font(FS_SMALL),
            text_color=FG_MUTED, anchor="w",
        ).pack(side="left", padx=S_3)

        # 兼容：保留"选择密码本文件"按钮
        ctk.CTkButton(
            header, text="选择密码本文件",
            font=font(FS_BODY, FW_MEDIUM),
            height=BTN_HEIGHT,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("folder-open", 16, FG_MAIN),
            compound="left",
            command=self._on_select_file,
        ).pack(side="right")

    def _build_tab_bar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=S_6, pady=(0, S_5))
        # 底部分隔线
        ctk.CTkFrame(bar, height=1, fg_color=BORDER, corner_radius=0).pack(
            fill="x", side="bottom"
        )
        self._tab_buttons = []
        for i, label in enumerate(["我的密码本", "编辑器", "版本记录"]):
            btn = ctk.CTkButton(
                bar, text=label,
                font=font(FS_BODY, FW_MEDIUM),
                height=36,
                corner_radius=0,
                fg_color="transparent",
                hover_color=BG_PAGE,
                command=lambda idx=i: self._show_tab(idx),
            )
            btn.pack(side="left", padx=(S_3 if i > 0 else 0, 0))
            self._tab_buttons.append(btn)

    def _show_tab(self, idx: int):
        self._active_tab = idx
        # 1. 刷新目标 Tab 内容（旧 Tab 仍可见，避免白屏）
        if idx == 0:
            self._render_library()
        elif idx == 1:
            self._render_editor()
        elif idx == 2:
            self._render_versions()
        # 2. 切换可见性 + 强制立即重绘
        for f in self._tab_frames:
            f.pack_forget()
        self._tab_frames[idx].pack(fill="both", expand=True)
        self.update_idletasks()  # 强制 Tk 立即处理几何计算和画布重绘
        # 3. 更新按钮样式
        for i, btn in enumerate(self._tab_buttons):
            btn.configure(text_color=PRIMARY if i == idx else FG_MUTED)

    # ======================== Tab 1: 我的密码本 ========================

    def _build_tab_library(self):
        self._lib_scroll = PageScrollFrame(
            self._tab_frames[0], fg_color="transparent", corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=FG_SUBTLE,
        )
        self._lib_scroll.pack(fill="both", expand=True)
        self._lib_content = ctk.CTkFrame(self._lib_scroll.content, fg_color="transparent")
        self._lib_content.pack(fill="x", padx=S_6, pady=S_5)

        # 工具栏
        toolbar = ctk.CTkFrame(self._lib_content, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, S_4))

        ctk.CTkButton(
            toolbar, text="新建密码本",
            font=font(FS_BODY, FW_MEDIUM), height=BTN_HEIGHT,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            image=get_ctk_image("plus", 16, PRIMARY_FG),
            compound="left",
            command=self._on_create,
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            toolbar, text="导入文件",
            font=font(FS_LABEL), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("file-text", 16, FG_MAIN),
            compound="left",
            command=self._on_import,
        ).pack(side="left")

        # 列表容器
        self._lib_list = ctk.CTkFrame(self._lib_content, fg_color="transparent")
        self._lib_list.pack(fill="x")

    def _render_library(self):
        for child in self._lib_list.winfo_children():
            child.destroy()
        try:
            books = self.controller.list_codebooks()
        except Exception:
            books = []
        cb_state = self.state.codebook
        loaded_id = cb_state.library_id if cb_state else None

        if not books:
            self._render_library_empty()
            return

        for meta in books:
            self._render_library_card(meta, meta.id == loaded_id)

    def _render_library_empty(self):
        empty = ctk.CTkFrame(self._lib_list, fg_color=BG_CARD,
                             corner_radius=RADIUS_CARD, border_color=BORDER, border_width=1)
        empty.pack(fill="x")
        ctk.CTkLabel(
            empty, image=get_ctk_image("book-open", 32, FG_SUBTLE), text="",
        ).pack(pady=(S_5, S_3))
        ctk.CTkLabel(
            empty, text="尚无密码本",
            font=font(FS_BODY, FW_MEDIUM), text_color=FG_MUTED,
        ).pack()
        ctk.CTkLabel(
            empty, text='点击上方"新建密码本"或"导入文件"开始',
            font=font(FS_SMALL), text_color=FG_SUBTLE,
        ).pack(pady=(2, S_5))

    def _render_library_card(self, meta: CodebookMeta, is_loaded: bool):
        card = ctk.CTkFrame(
            self._lib_list, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        card.pack(fill="x", pady=(0, S_3))
        if is_loaded:
            bar = ctk.CTkFrame(card, width=3, corner_radius=0, fg_color=PRIMARY)
            bar.place(x=0, y=0, relheight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_4)

        # 第一行：图标 + 名称 + 徽标
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, S_3))

        ctk.CTkLabel(
            row1, image=get_ctk_image("book-open", 20, PRIMARY if is_loaded else FG_MUTED),
            text="",
        ).pack(side="left", padx=(0, S_2))

        ctk.CTkLabel(
            row1, text=meta.name,
            font=font(FS_BODY, "bold"), text_color=FG_MAIN,
        ).pack(side="left")

        if is_loaded:
            self._make_badge(row1, "check-circle", "已加载", SUCCESS, BG_SUCCESS)

        # 操作按钮
        btn_row = ctk.CTkFrame(row1, fg_color="transparent")
        btn_row.pack(side="right")

        def _btn(text, icon, cmd, danger=False):
            ctk.CTkButton(
                btn_row, text=text,
                font=font(FS_LABEL), height=BTN_HEIGHT_SM,
                corner_radius=RADIUS_BTN,
                fg_color=BG_CARD,
                text_color=ERROR if danger else FG_MAIN,
                border_color=BORDER, border_width=1,
                hover_color=BG_PAGE,
                image=get_ctk_image(icon, 16, ERROR if danger else FG_MAIN),
                compound="left",
                command=cmd,
            ).pack(side="left", padx=(0, S_2))

        if is_loaded:
            _btn("编辑", "file-text", lambda m=meta: self._on_edit(m))
        else:
            _btn("加载", "check", lambda m=meta: self._on_load(m))
        _btn("复制", "copy", lambda m=meta: self._on_duplicate(m))
        _btn("重命名", "file-text", lambda m=meta: self._on_rename(m))
        _btn("导出", "download", lambda m=meta: self._on_export(m))
        _btn("删除", "trash", lambda m=meta: self._on_delete(m), danger=True)

        # 第二行：元信息
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x")

        meta_items = [
            f"{meta.exact_rule_count} 条精确规则",
            f"{meta.regex_rule_count} 条正则规则",
            f"{meta.version_count} 个版本",
        ]
        if meta.updated_at:
            meta_items.append(f"更新于 {meta.updated_at[:16].replace('T', ' ')}")
        for i, item in enumerate(meta_items):
            if i > 0:
                ctk.CTkFrame(row2, width=1, height=12, fg_color=BORDER, corner_radius=0).pack(
                    side="left", padx=S_3
                )
            ctk.CTkLabel(
                row2, text=item,
                font=font(FS_SMALL), text_color=FG_MUTED,
            ).pack(side="left")

    # ======================== Tab 2: 编辑器 ========================

    def _build_tab_editor(self):
        self._ed_scroll = PageScrollFrame(
            self._tab_frames[1], fg_color="transparent", corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=FG_SUBTLE,
        )
        self._ed_scroll.pack(fill="both", expand=True)
        self._ed_content = ctk.CTkFrame(self._ed_scroll.content, fg_color="transparent")
        self._ed_content.pack(fill="x", padx=S_6, pady=S_5)

    def _render_editor(self):
        for child in self._ed_content.winfo_children():
            child.destroy()

        cb = self.state.codebook
        if not cb or not cb.is_loaded:
            self._render_editor_empty()
            return

        # 注意：不从 codebook 状态覆盖 _edit_rules
        # _edit_rules 仅在加载密码本时（_on_load/_on_select_file）初始化，
        # 之后由编辑器内增删改操作维护，避免未保存的编辑被渲染覆盖。

        # 头部：名称 + 版本 + 校验徽标
        header = ctk.CTkFrame(self._ed_content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_4))

        ctk.CTkLabel(
            header, image=get_ctk_image("file-text", 20, PRIMARY), text="",
        ).pack(side="left", padx=(0, S_2))

        name = cb.library_name or os.path.basename(cb.path or "")
        ctk.CTkLabel(
            header, text=name,
            font=font(FS_BODY, "bold"), text_color=FG_MAIN,
        ).pack(side="left")

        if cb.version:
            ctk.CTkLabel(
                header, text=f"- {cb.version}",
                font=font(FS_SMALL), text_color=FG_MUTED,
            ).pack(side="left", padx=(S_2, 0))

        # 校验徽标
        self._ed_badge_frame = ctk.CTkFrame(header, fg_color="transparent")
        self._ed_badge_frame.pack(side="right")
        self._update_validation_badge()

        # 校验消息列表
        if self._validation_messages:
            msg_card = ctk.CTkFrame(
                self._ed_content, fg_color=BG_CARD,
                corner_radius=RADIUS_CARD,
                border_color=BORDER, border_width=1,
            )
            msg_card.pack(fill="x", pady=(0, S_4))
            bar = ctk.CTkFrame(msg_card, width=3, corner_radius=0, fg_color=WARNING)
            bar.place(x=0, y=0, relheight=1)
            msg_inner = ctk.CTkFrame(msg_card, fg_color="transparent")
            msg_inner.pack(fill="x", padx=S_5, pady=S_4)
            for msg in self._validation_messages:
                row = ctk.CTkFrame(msg_inner, fg_color="transparent")
                row.pack(fill="x", pady=(2, 0))
                color = ERROR if msg.startswith("ERROR") else WARNING
                ctk.CTkFrame(row, width=8, height=8, corner_radius=4, fg_color=color).pack(
                    side="left", padx=(0, S_3), pady=(S_2, 0), anchor="n"
                )
                ctk.CTkLabel(
                    row, text=msg,
                    font=font(FS_BODY), text_color=FG_MAIN, anchor="w",
                ).pack(side="left", fill="x", expand=True)

        # 规则表格
        table_card = ctk.CTkFrame(
            self._ed_content, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        table_card.pack(fill="x", pady=(0, S_4))
        table_inner = ctk.CTkFrame(table_card, fg_color="transparent")
        table_inner.pack(fill="x", padx=S_4, pady=S_4)

        # 表头
        hdr = ctk.CTkFrame(table_inner, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, S_2))
        for col, (text, w) in enumerate([
            ("#", 40), ("类型", 60), ("原文", None), ("脱敏词", None), ("注释", 120), ("", 40)
        ]):
            lbl = ctk.CTkLabel(
                hdr, text=text,
                font=font(FS_SMALL, "bold"), text_color=FG_MUTED, anchor="w",
            )
            if w:
                lbl.configure(width=w)
                lbl.pack(side="left", padx=(0, S_2))
            else:
                lbl.pack(side="left", fill="x", expand=True, padx=(0, S_2))

        # 规则行
        self._rule_rows = []
        for i, rule in enumerate(self._edit_rules):
            row = self._build_rule_row(table_inner, i, rule)
            self._rule_rows.append(row)

        # 添加规则按钮
        add_row = ctk.CTkFrame(self._ed_content, fg_color="transparent")
        add_row.pack(fill="x", pady=(0, S_4))

        ctk.CTkButton(
            add_row, text="添加精确规则",
            font=font(FS_LABEL), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("plus", 16, FG_MAIN),
            compound="left",
            command=lambda: self._on_add_rule("exact"),
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            add_row, text="添加正则规则",
            font=font(FS_LABEL), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("plus", 16, FG_MAIN),
            compound="left",
            command=lambda: self._on_add_rule("regex"),
        ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            add_row, text="批量粘贴",
            font=font(FS_LABEL), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("clipboard-list", 16, FG_MAIN),
            compound="left",
            command=self._on_paste_rules,
        ).pack(side="left")

        # 底部操作
        bottom = ctk.CTkFrame(self._ed_content, fg_color="transparent")
        bottom.pack(fill="x")

        if self.state.codebook and self.state.codebook.from_library:
            ctk.CTkButton(
                bottom, text="保存（生成新版本）",
                font=font(FS_BODY, FW_MEDIUM), height=BTN_HEIGHT,
                corner_radius=RADIUS_BTN,
                fg_color=PRIMARY, text_color=PRIMARY_FG,
                hover_color=PRIMARY_HOVER,
                image=get_ctk_image("check-circle", 16, PRIMARY_FG),
                compound="left",
                command=self._on_save,
            ).pack(side="left", padx=(0, S_3))

        ctk.CTkButton(
            bottom, text="另存为新密码本",
            font=font(FS_LABEL), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MAIN,
            border_color=BORDER, border_width=1,
            hover_color=BG_PAGE,
            image=get_ctk_image("plus", 16, FG_MAIN),
            compound="left",
            command=self._on_save_as_new,
        ).pack(side="left")

    def _render_editor_empty(self):
        empty = ctk.CTkFrame(self._ed_content, fg_color=BG_CARD,
                             corner_radius=RADIUS_CARD, border_color=BORDER, border_width=1)
        empty.pack(fill="x")
        ctk.CTkLabel(
            empty, image=get_ctk_image("file-text", 32, FG_SUBTLE), text="",
        ).pack(pady=(S_5, S_3))
        ctk.CTkLabel(
            empty, text="未加载密码本",
            font=font(FS_BODY, FW_MEDIUM), text_color=FG_MUTED,
        ).pack()
        ctk.CTkLabel(
            empty, text='请在"我的密码本"中选择或新建密码本',
            font=font(FS_SMALL), text_color=FG_SUBTLE,
        ).pack(pady=(2, S_5))

    def _build_rule_row(self, parent, index: int, rule: CodebookRule):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, S_2))

        # 序号
        ctk.CTkLabel(
            row, text=str(index + 1),
            font=font(FS_SMALL), text_color=FG_MUTED, width=40, anchor="w",
        ).pack(side="left", padx=(0, S_2))

        # 类型标签
        tag_color = WARNING if rule.rule_type == "regex" else SUCCESS
        tag_bg = BG_WARNING if rule.rule_type == "regex" else BG_SUCCESS
        ctk.CTkLabel(
            row, text="正则" if rule.rule_type == "regex" else "精确",
            font=font(11, "bold"), text_color=tag_color,
            fg_color=tag_bg, corner_radius=RADIUS_SM,
            width=50, height=20,
        ).pack(side="left", padx=(0, S_2))

        # 原文输入
        orig_entry = ctk.CTkEntry(
            row, width=180,
            font=font(FS_SMALL), height=32,
            corner_radius=RADIUS_SM,
            fg_color=BG_PAGE, border_color=BORDER, text_color=FG_MAIN,
        )
        orig_entry.insert(0, rule.display_original)
        orig_entry.pack(side="left", fill="x", expand=True, padx=(0, S_2))

        # 脱敏词输入
        repl_entry = ctk.CTkEntry(
            row, width=150,
            font=font(FS_SMALL), height=32,
            corner_radius=RADIUS_SM,
            fg_color=BG_PAGE, border_color=BORDER, text_color=FG_MAIN,
        )
        repl_entry.insert(0, rule.replacement)
        repl_entry.pack(side="left", fill="x", expand=True, padx=(0, S_2))

        # 注释输入
        comment_entry = ctk.CTkEntry(
            row, width=120,
            font=font(FS_SMALL), height=32,
            corner_radius=RADIUS_SM,
            fg_color=BG_PAGE, border_color=BORDER, text_color=FG_MAIN,
            placeholder_text="可选",
        )
        if rule.comment:
            comment_entry.insert(0, rule.comment)
        comment_entry.pack(side="left", padx=(0, S_2))

        # 删除按钮
        ctk.CTkButton(
            row, text="",
            image=get_ctk_image("trash", 16, FG_SUBTLE),
            width=32, height=32,
            corner_radius=RADIUS_SM,
            fg_color="transparent", hover_color=BG_PAGE,
            command=lambda idx=index: self._on_delete_rule(idx),
        ).pack(side="left")

        return (orig_entry, repl_entry, comment_entry, rule.rule_type)

    def _collect_rules(self) -> list[CodebookRule]:
        """从输入框收集规则列表（跳过空行，用于保存/校验）。"""
        rules = []
        for orig_entry, repl_entry, comment_entry, rule_type in self._rule_rows:
            original = orig_entry.get().strip()
            replacement = repl_entry.get().strip()
            comment = comment_entry.get().strip()
            if not original or not replacement:
                continue
            if rule_type == "regex":
                original = f"{REGEX_PREFIX}{original}" if not original.startswith(REGEX_PREFIX) else original
            rules.append(CodebookRule(
                rule_type=rule_type,
                original=original,
                replacement=replacement,
                comment=comment,
            ))
        return rules

    def _sync_edit_rules(self):
        """从 UI 输入框同步 _edit_rules（保留空行，用于增删改前保存当前编辑状态）。"""
        if not self._rule_rows:
            return
        synced = []
        for orig_entry, repl_entry, comment_entry, rule_type in self._rule_rows:
            original = orig_entry.get().strip()
            replacement = repl_entry.get().strip()
            comment = comment_entry.get().strip()
            if rule_type == "regex" and original and not original.startswith(REGEX_PREFIX):
                original = f"{REGEX_PREFIX}{original}"
            synced.append(CodebookRule(
                rule_type=rule_type,
                original=original,
                replacement=replacement,
                comment=comment,
            ))
        self._edit_rules = synced

    def _validate_edit_rules(self):
        """收集规则并执行校验，更新徽标。"""
        from docmask.core.codebook import Codebook as _CB
        rules = self._collect_rules()
        cb = _CB.__new__(_CB)
        cb.filepath = ""
        cb.forward_map = {}
        cb.reverse_map = {}
        cb._sorted_keys = []
        cb.regex_rules = []
        cb._line_numbers = {}
        cb._regex_line_numbers = []
        cb._raw_content = ""
        self._validation_messages = cb.update_rules(rules)
        self._update_validation_badge()

    def _update_validation_badge(self):
        for child in self._ed_badge_frame.winfo_children():
            child.destroy()
        msgs = self._validation_messages
        error_count = sum(1 for m in msgs if m.startswith("ERROR"))
        warning_count = sum(1 for m in msgs if m.startswith("WARNING"))
        if error_count > 0:
            self._make_badge(self._ed_badge_frame, "alert-triangle", f"{error_count} 项错误", ERROR, BG_ERROR)
        elif warning_count > 0:
            self._make_badge(self._ed_badge_frame, "alert-triangle", f"{warning_count} 项警告", WARNING, BG_WARNING)
        else:
            self._make_badge(self._ed_badge_frame, "check-circle", "校验通过", SUCCESS, BG_SUCCESS)

    # ======================== Tab 3: 版本记录 ========================

    def _build_tab_versions(self):
        self._ver_scroll = PageScrollFrame(
            self._tab_frames[2], fg_color="transparent", corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=FG_SUBTLE,
        )
        self._ver_scroll.pack(fill="both", expand=True)
        self._ver_content = ctk.CTkFrame(self._ver_scroll.content, fg_color="transparent")
        self._ver_content.pack(fill="x", padx=S_6, pady=S_5)

    def _render_versions(self):
        for child in self._ver_content.winfo_children():
            child.destroy()

        cb = self.state.codebook
        if not cb or not cb.is_loaded or not cb.from_library:
            self._render_versions_empty()
            return

        # 头部
        header = ctk.CTkFrame(self._ver_content, fg_color="transparent")
        header.pack(fill="x", pady=(0, S_4))

        ctk.CTkLabel(
            header, image=get_ctk_image("rotate-ccw", 20, PRIMARY), text="",
        ).pack(side="left", padx=(0, S_2))

        name = cb.library_name or ""
        ctk.CTkLabel(
            header, text=name,
            font=font(FS_BODY, "bold"), text_color=FG_MAIN,
        ).pack(side="left")

        try:
            versions = self.controller.list_versions(cb.library_id)
        except Exception:
            versions = []

        ctk.CTkLabel(
            header, text=f"- 共 {len(versions)} 个版本",
            font=font(FS_SMALL), text_color=FG_MUTED,
        ).pack(side="left", padx=(S_2, 0))

        if not versions:
            self._render_versions_empty()
            return

        # 时间线卡片
        card = ctk.CTkFrame(
            self._ver_content, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=S_5, pady=S_4)

        current_version = cb.version
        for i, ver in enumerate(versions):
            self._render_version_item(inner, ver, ver.version_id == current_version, i > 0)

    def _render_versions_empty(self):
        empty = ctk.CTkFrame(self._ver_content, fg_color=BG_CARD,
                             corner_radius=RADIUS_CARD, border_color=BORDER, border_width=1)
        empty.pack(fill="x")
        ctk.CTkLabel(
            empty, image=get_ctk_image("rotate-ccw", 32, FG_SUBTLE), text="",
        ).pack(pady=(S_5, S_3))
        ctk.CTkLabel(
            empty, text="尚无版本记录",
            font=font(FS_BODY, FW_MEDIUM), text_color=FG_MUTED,
        ).pack()
        ctk.CTkLabel(
            empty, text="在编辑器中保存密码本后将自动生成版本快照",
            font=font(FS_SMALL), text_color=FG_SUBTLE,
        ).pack(pady=(2, S_5))

    def _render_version_item(self, parent, ver: VersionInfo, is_current: bool, show_sep: bool):
        if show_sep:
            ctk.CTkFrame(parent, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x", pady=S_4)

        item = ctk.CTkFrame(parent, fg_color="transparent")
        item.pack(fill="x")

        # 圆点
        dot = ctk.CTkFrame(
            item, width=10, height=10, corner_radius=5,
            fg_color=SUCCESS if is_current else PRIMARY,
        )
        dot.pack(side="left", padx=(0, S_4), pady=(S_2, 0), anchor="n")

        # 内容
        content = ctk.CTkFrame(item, fg_color="transparent")
        content.pack(side="left", fill="x", expand=True)

        # 版本号 + 徽标
        row1 = ctk.CTkFrame(content, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(
            row1, text=ver.version_id,
            font=font(FS_BODY, "bold"), text_color=FG_MAIN,
        ).pack(side="left")
        if is_current:
            self._make_badge(row1, "check-circle", "当前", SUCCESS, BG_SUCCESS)

        # 时间 + 规则数
        time_str = ver.created_at[:19].replace("T", " ") if ver.created_at else ""
        ctk.CTkLabel(
            row1, text=f"{time_str} · {ver.exact_rule_count} 精确 + {ver.regex_rule_count} 正则",
            font=font(FS_SMALL), text_color=FG_MUTED,
        ).pack(side="left", padx=(S_3, 0))

        # 变更摘要
        ctk.CTkLabel(
            content, text=ver.change_summary,
            font=font(FS_BODY), text_color=FG_MAIN if not is_current else FG_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(S_2, 0))

        # 恢复按钮
        if not is_current:
            ctk.CTkButton(
                content, text="恢复此版本",
                font=font(FS_LABEL), height=BTN_HEIGHT_SM,
                corner_radius=RADIUS_BTN,
                fg_color=BG_CARD, text_color=FG_MAIN,
                border_color=BORDER, border_width=1,
                hover_color=BG_PAGE,
                image=get_ctk_image("rotate-ccw", 16, FG_MAIN),
                compound="left",
                command=lambda v=ver: self._on_restore(v),
            ).pack(anchor="w", pady=(S_3, 0))

    # ======================== 辅助方法 ========================

    def _make_card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent, fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER, border_width=1,
        )

    def _make_badge(self, parent, icon_name, text, text_color, bg_color):
        badge = ctk.CTkFrame(parent, fg_color=bg_color, corner_radius=RADIUS_PILL)
        badge.pack(side="left", padx=S_3)
        ctk.CTkLabel(
            badge, image=get_ctk_image(icon_name, 14, text_color), text="",
        ).pack(side="left", padx=(10, 4))
        ctk.CTkLabel(
            badge, text=text,
            font=font(FS_SMALL, FW_MEDIUM), text_color=text_color,
        ).pack(side="left", padx=(0, 10))

    # ======================== 事件处理 ========================

    def _on_select_file(self):
        """兼容：从外部文件加载密码本。"""
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            cb_state = self.controller.load_codebook(path)
            self.state.codebook = cb_state
            self._edit_rules = cb_state.edit_rules or (
                cb_state.codebook.to_rules() if cb_state.codebook else []
            )
            self._validation_messages = cb_state.messages
            self._show_tab(1)

    def _on_create(self):
        name = simpledialog.askstring("新建密码本", "请输入密码本名称：", parent=self)
        if not name:
            return
        try:
            meta = self.controller.create_codebook(name)
            # 自动加载并跳转到编辑器
            self._on_load(meta, navigate=False)
            self._show_tab(1)
        except Exception as e:
            messagebox.showerror("错误", f"创建失败：{e}", parent=self)

    def _on_import(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not path:
            return
        name = simpledialog.askstring("导入密码本", "请输入密码本名称：", parent=self,
                                      initialvalue=os.path.splitext(os.path.basename(path))[0])
        if not name:
            return
        try:
            self.controller.import_codebook(path, name)
            self._render_library()
        except Exception as e:
            messagebox.showerror("错误", f"导入失败：{e}", parent=self)

    def _on_load(self, meta: CodebookMeta, navigate: bool = True):
        try:
            cb_state = self.controller.load_library_codebook(meta.id)
            self._edit_rules = cb_state.edit_rules
            self._validation_messages = cb_state.messages
            self._render_library()
            if navigate and self.on_navigate:
                self.on_navigate("workbench")
        except Exception as e:
            messagebox.showerror("错误", f"加载失败：{e}", parent=self)

    def _on_edit(self, meta: CodebookMeta):
        self._on_load(meta, navigate=False)
        self._show_tab(1)

    def _on_duplicate(self, meta: CodebookMeta):
        name = simpledialog.askstring("复制密码本", "请输入新密码本名称：",
                                      parent=self, initialvalue=f"{meta.name} 副本")
        if not name:
            return
        try:
            self.controller.duplicate_codebook(meta.id, name)
            self._render_library()
        except Exception as e:
            messagebox.showerror("错误", f"复制失败：{e}", parent=self)

    def _on_rename(self, meta: CodebookMeta):
        name = simpledialog.askstring(
            "重命名密码本", "请输入新名称：", parent=self, initialvalue=meta.name,
        )
        if not name or name == meta.name:
            return
        try:
            self.controller.rename_codebook(meta.id, name)
            # 如果重命名的是当前加载的，同步更新状态
            if self.state.codebook and self.state.codebook.library_id == meta.id:
                self.state.codebook.library_name = name
            self._render_library()
        except Exception as e:
            messagebox.showerror("错误", f"重命名失败：{e}", parent=self)

    def _on_export(self, meta: CodebookMeta):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"{meta.name}.txt",
        )
        if not path:
            return
        try:
            self.controller.export_codebook(meta.id, path)
            messagebox.showinfo("成功", f"已导出到：{path}", parent=self)
        except FileExistsError:
            messagebox.showerror("错误", "目标文件已存在，请选择其他路径", parent=self)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}", parent=self)

    def _on_delete(self, meta: CodebookMeta):
        if not show_confirm(
            self, title="删除密码本",
            message=f'确定要删除"{meta.name}"吗？\n所有版本记录将一并删除，此操作不可撤销。',
            confirm_text="删除", cancel_text="取消", danger=True,
        ):
            return
        try:
            self.controller.delete_codebook(meta.id)
            # 如果删除的是当前加载的，清除状态
            if self.state.codebook and self.state.codebook.library_id == meta.id:
                self.state.codebook = type(self.state.codebook)()
            self._render_library()
        except Exception as e:
            messagebox.showerror("错误", f"删除失败：{e}", parent=self)

    def _on_add_rule(self, rule_type: str):
        self._sync_edit_rules()
        rule = CodebookRule(rule_type=rule_type, original="", replacement="")
        self._edit_rules.append(rule)
        self._render_editor()
        self._validate_edit_rules()

    def _on_delete_rule(self, idx: int):
        self._sync_edit_rules()
        if 0 <= idx < len(self._edit_rules):
            self._edit_rules.pop(idx)
            self._render_editor()
            self._validate_edit_rules()

    def _on_paste_rules(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("批量粘贴规则")
        dialog.geometry("500x350")
        dialog.transient(self)
        dialog.grab_set()
        dialog.after(10, lambda: dialog.geometry(f"+{self.winfo_rootx()+100}+{self.winfo_rooty()+100}"))

        ctk.CTkLabel(
            dialog, text="每行一条规则，格式：原文==>脱敏词",
            font=font(FS_SMALL), text_color=FG_MUTED,
        ).pack(anchor="w", padx=S_5, pady=(S_4, S_2))

        textbox = ctk.CTkTextbox(dialog, font=font(FS_SMALL), height=200)
        textbox.pack(fill="both", expand=True, padx=S_5, pady=(0, S_4))

        def _confirm():
            self._sync_edit_rules()
            text = textbox.get("1.0", "end").strip()
            added = 0
            skipped = 0
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(COMMENT_PREFIX):
                    continue
                if CODEBOOK_SEPARATOR not in line:
                    skipped += 1
                    continue
                parts = line.split(CODEBOOK_SEPARATOR, 1)
                original = parts[0].strip()
                replacement = parts[1].strip()
                if not original or not replacement:
                    skipped += 1
                    continue
                rt = "regex" if original.startswith(REGEX_PREFIX) else "exact"
                self._edit_rules.append(CodebookRule(
                    rule_type=rt, original=original, replacement=replacement,
                ))
                added += 1
            dialog.destroy()
            if added > 0:
                self._render_editor()
                self._validate_edit_rules()
            if skipped > 0:
                messagebox.showwarning(
                    "批量粘贴",
                    f"成功添加 {added} 条规则，跳过 {skipped} 行无法识别的规则。",
                    parent=self,
                )

        ctk.CTkButton(
            dialog, text="添加",
            font=font(FS_BODY, FW_MEDIUM), height=BTN_HEIGHT_SM,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            command=_confirm,
        ).pack(side="right", padx=S_5, pady=(0, S_4))

    def _on_save(self):
        cb = self.state.codebook
        if not cb or not cb.library_id:
            return
        rules = self._collect_rules()
        try:
            version, messages = self.controller.save_codebook_to_library(cb.library_id, rules)
            self._validation_messages = messages
            # 重新加载并同步编辑器规则
            cb_state = self.controller.load_library_codebook(cb.library_id)
            self._edit_rules = cb_state.edit_rules
            self._render_editor()
            messagebox.showinfo("保存成功",
                f"已生成新版本：{version.version_id}\n{version.change_summary}",
                parent=self)
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{e}", parent=self)

    def _on_save_as_new(self):
        rules = self._collect_rules()
        name = simpledialog.askstring("另存为新密码本", "请输入新密码本名称：", parent=self)
        if not name:
            return
        try:
            meta = self.controller.create_codebook(name)
            self.controller.save_codebook_to_library(meta.id, rules)
            self.controller.load_library_codebook(meta.id)
            self._show_tab(0)
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{e}", parent=self)

    def _on_restore(self, ver: VersionInfo):
        cb = self.state.codebook
        if not cb or not cb.library_id:
            return
        if not show_confirm(
            self, title="恢复版本",
            message=f"确定要恢复到版本 {ver.version_id} 吗？\n当前版本将被覆盖为新版本。",
            confirm_text="恢复", cancel_text="取消",
        ):
            return
        try:
            self.controller.restore_version(cb.library_id, ver.version_id)
            self.controller.load_library_codebook(cb.library_id)
            self._render_versions()
            messagebox.showinfo("恢复成功", f"已恢复到版本 {ver.version_id}", parent=self)
        except Exception as e:
            messagebox.showerror("错误", f"恢复失败：{e}", parent=self)

    # ======================== 刷新 ========================

    def on_show(self):
        """页面被显示时刷新当前 Tab。"""
        self._show_tab(self._active_tab)
