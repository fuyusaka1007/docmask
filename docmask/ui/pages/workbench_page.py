"""工作台页面：核心操作流程"""
import os
import customtkinter as ctk
from tkinter import filedialog

from docmask.ui.theme import (
    font, FS_SECTION, FS_BODY, FS_LABEL, FS_SMALL, FS_BUTTON,
    S_2, S_3, S_4, S_5, S_6, BTN_HEIGHT, BTN_HEIGHT_SM,
    RADIUS_BTN, RADIUS_CARD, RADIUS_INPUT,
    BG_PAGE, BG_CARD, BG_INPUT, BORDER, BORDER_LIGHT,
    FG_MAIN, FG_MUTED, FG_SUBTLE,
    PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
    SUCCESS, WARNING, ERROR, INFO,
    BG_SUCCESS, BG_WARNING, BG_ERROR, BG_INFO,
    MAX_WIDTH_WORKBENCH,
)
from docmask.ui.state import AppState, FileStatus, FileItem, Mode
from docmask.ui.widgets.path_picker import PathPicker
from docmask.ui.widgets.file_queue import FileQueue
from docmask.ui.widgets.status_badge import StatusBadge
from docmask.ui.widgets.dialogs import show_confirm, ConflictDialog
from docmask.ui.widgets.icon import get_ctk_image
from docmask.ui.widgets.scroll_frame import PageScrollFrame

class WorkbenchPage(ctk.CTkFrame):
    """工作台主页面"""

    def __init__(self, master, state: AppState, controller, on_navigate: callable = None, **kwargs):
        super().__init__(master, fg_color=BG_PAGE, corner_radius=0, **kwargs)
        self.state = state
        self.controller = controller
        self.on_navigate = on_navigate

        self._build_header()
        self._build_scroll_area()
        self._build_execute_bar()

        # 注册设置变更监听器，使设置页修改后工作台控件能同步刷新
        self.state.add_listener(self._on_settings_changed)

    # ======================== 布局 ========================

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(S_5, S_2))

        self._header_content = ctk.CTkFrame(header, fg_color="transparent")
        self._header_content.pack(fill="x", padx=S_6)

        # 标题
        title_frame = ctk.CTkFrame(self._header_content, fg_color="transparent")
        title_frame.pack(side="left")

        ctk.CTkLabel(
            title_frame, text="工作台",
            font=font(20, "bold"),
            text_color=FG_MAIN,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame, text="创建一个脱敏或恢复任务",
            font=font(FS_BODY),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(anchor="w")

        # 状态指示
        self._status_label = ctk.CTkLabel(
            self._header_content, text="就绪", image=get_ctk_image("check-circle", 16, SUCCESS), compound="left",
            font=font(FS_LABEL),
            text_color=SUCCESS,
        )
        self._status_label.pack(side="right")

    def _build_scroll_area(self):
        self._scroll = PageScrollFrame(
            self, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=FG_SUBTLE,
        )
        self._scroll.pack(fill="both", expand=True)

        self._scroll_content = ctk.CTkFrame(
            self._scroll.content, fg_color="transparent",
        )
        self._scroll_content.pack(fill="x", padx=S_6)

        self._build_mode_card(self._scroll_content)
        self._build_codebook_card(self._scroll_content)
        self._build_file_queue_card(self._scroll_content)
        self._build_output_card(self._scroll_content)

        # 底部留白，避免最后一张卡片紧贴固定执行栏
        ctk.CTkFrame(self._scroll_content, fg_color="transparent", height=80).pack()

    def _build_mode_card(self, parent):
        card = self._make_card(parent)
        card.pack(fill="x", pady=(0, 20))

        self._make_section_label(card, "任务模式")

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=S_5, pady=(0, S_3))

        self._mode_mask_btn = ctk.CTkButton(
            btn_frame, text="脱敏文档", image=get_ctk_image("shield-check", 16, PRIMARY_FG), compound="left",
            font=font(FS_BODY, "bold"),
            height=38, width=120,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            command=lambda: self._switch_mode(Mode.MASK),
        )
        self._mode_mask_btn.pack(side="left", padx=(0, 2))

        self._mode_restore_btn = ctk.CTkButton(
            btn_frame, text="恢复文档",
            font=font(FS_BODY, "bold"),
            height=38, width=120,
            corner_radius=RADIUS_BTN,
            fg_color=BG_CARD, text_color=FG_MUTED,
            border_color=BORDER, border_width=1,
            hover_color=("gray90", "gray25"),
            command=lambda: self._switch_mode(Mode.RESTORE),
        )
        self._mode_restore_btn.pack(side="left")

        self._mode_hint = ctk.CTkLabel(
            card,
            text="脱敏：替换敏感信息，可使用同一密码本恢复",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
            anchor="w",
        )
        self._mode_hint.pack(anchor="w", padx=S_5, pady=(0, S_5))

    def _build_codebook_card(self, parent):
        card = self._make_card(parent)
        card.pack(fill="x", pady=(0, 20))

        self._make_section_label(card, "1. 密码本")

        self._codebook_picker = PathPicker(
            card,
            placeholder="请选择 .txt 密码本",
            button_text="选择文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            on_change=self._on_codebook_change,
        )
        self._codebook_picker.pack(fill="x", padx=S_5, pady=(0, S_4))

        # 状态行
        self._cb_status_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._cb_status_frame.pack(fill="x", padx=S_5)

        self._cb_dot = ctk.CTkLabel(
            self._cb_status_frame, text="",
            font=font(FS_SMALL),
            width=12,
        )
        self._cb_dot.pack(side="left")

        self._cb_status_text = ctk.CTkLabel(
            self._cb_status_frame,
            text="请选择密码本",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
            anchor="w",
        )
        self._cb_status_text.pack(side="left", padx=(S_2, 0))

        # 正则警告（默认隐藏）
        self._cb_warning = ctk.CTkFrame(
            card, fg_color=BG_WARNING, corner_radius=RADIUS_INPUT,
            border_color=("#F3DFC0", "#4A3517"), border_width=1,
        )
        ctk.CTkLabel(
            self._cb_warning,
            text="  !  正则规则不可逆，恢复时无法还原正则匹配的原始内容",
            font=font(FS_SMALL),
            text_color=WARNING,
            anchor="w",
        ).pack(fill="x", padx=S_3, pady=S_2)
        # 默认隐藏

    def _build_file_queue_card(self, parent):
        card = self._make_card(parent)
        card.pack(fill="x", pady=(0, 20))

        self._make_section_label(card, "2. 待处理文件")

        self._file_queue = FileQueue(
            card,
            on_remove=self._on_remove_file,
            on_add_files=self._on_add_files,
            on_add_folder=self._on_add_folder,
            on_clear=self._on_clear_files,
            on_drop_files=self._on_drop_files,
        )
        self._file_queue.pack(fill="x", padx=S_5, pady=(0, S_5))

        self._fmt_vars = {}
        for fmt in ["docx", "doc", "txt"]:
            var = ctk.StringVar(value="on")
            cb = ctk.CTkCheckBox(
                self._file_queue.toolbar, text=fmt.upper(), font=font(FS_BODY),
                variable=var, onvalue="on", offvalue="off",
                command=self._on_filter_change, text_color=FG_MUTED,
                checkbox_width=16, checkbox_height=16,
            )
            cb.pack(side="left", padx=(S_4, 0))
            self._fmt_vars[fmt] = var

    def _build_output_card(self, parent):
        card = self._make_card(parent)
        card.pack(fill="x", pady=(0, 20))

        self._make_section_label(card, "3. 输出设置")

        # 单选
        radio_frame = ctk.CTkFrame(card, fg_color="transparent")
        radio_frame.pack(fill="x", padx=S_5, pady=(0, S_3))

        self._output_var = ctk.StringVar(value="same_dir")

        ctk.CTkRadioButton(
            radio_frame, text="保存到原文件所在目录",
            font=font(FS_BODY),
            variable=self._output_var, value="same_dir",
            command=self._on_output_mode_change,
            text_color=FG_MAIN, fg_color=PRIMARY,
        ).pack(side="left", padx=(0, S_5))

        ctk.CTkRadioButton(
            radio_frame, text="指定目录",
            font=font(FS_BODY),
            variable=self._output_var, value="custom",
            command=self._on_output_mode_change,
            text_color=FG_MAIN, fg_color=PRIMARY,
        ).pack(side="left")

        # 目录选择
        self._output_picker = PathPicker(
            card,
            placeholder="选择输出目录...",
            button_text="浏览",
            file_mode=False,
            on_change=self._on_output_dir_change,
        )
        self._output_picker.pack(fill="x", padx=S_5, pady=(0, S_2))
        self._output_picker.set_enabled(False)

        # 提示
        ctk.CTkLabel(
            card,
            text="文件名自动添加后缀；重名时自动追加序号，不覆盖原文件",
            font=font(FS_SMALL),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(anchor="w", padx=S_5, pady=(0, S_3))

        # 覆盖率报告
        self._report_var = ctk.StringVar(value="on")
        self._report_cb = ctk.CTkCheckBox(
            card, text="生成覆盖率报告（仅脱敏）",
            font=font(FS_BODY),
            variable=self._report_var, onvalue="on", offvalue="off",
            text_color=FG_MAIN, fg_color=PRIMARY,
        )
        self._report_cb.pack(anchor="w", padx=S_5, pady=(0, S_5))

    def _build_execute_bar(self):
        """底部执行栏"""
        bar = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=0,
            border_color=BORDER,
            border_width=1,
        )
        bar.pack(fill="x", side="bottom")

        content = ctk.CTkFrame(bar, fg_color="transparent")
        content.pack(fill="x", padx=S_6, pady=S_4)

        # 左侧状态
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left")

        self._exec_info = ctk.CTkLabel(
            left, text="",
            font=font(FS_BODY),
            text_color=FG_MUTED,
            anchor="w",
        )
        self._exec_info.pack(anchor="w")

        # 进度条（任务运行时显示）
        self._progress_bar = ctk.CTkProgressBar(
            left, height=6,
            fg_color=BORDER_LIGHT,
            progress_color=PRIMARY,
            width=200,
        )
        # 默认不显示

        # 右侧按钮
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.pack(side="right")

        self._stop_btn = ctk.CTkButton(
            right, text="停止", image=get_ctk_image("square", 16, ERROR), compound="left",
            font=font(FS_BODY),
            height=BTN_HEIGHT, width=80,
            corner_radius=RADIUS_BTN,
            fg_color="transparent",
            text_color=ERROR,
            border_color=ERROR, border_width=1,
            hover_color=BG_ERROR,
            command=self._on_stop,
        )
        # 默认隐藏

        self._execute_btn = ctk.CTkButton(
            right, text="预检并执行脱敏", image=get_ctk_image("play", 16, PRIMARY_FG), compound="left",
            font=font(FS_BUTTON, "bold"),
            height=BTN_HEIGHT, width=160,
            corner_radius=RADIUS_BTN,
            fg_color=PRIMARY, text_color=PRIMARY_FG,
            hover_color=PRIMARY_HOVER,
            command=self._on_execute,
        )
        self._execute_btn.pack(side="right")

        self._update_execute_bar()

    # ======================== 辅助 ========================

    def _make_card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=BG_CARD,
            corner_radius=RADIUS_CARD,
            border_color=BORDER,
            border_width=1,
        )

    def _make_section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=font(FS_LABEL, "bold"),
            text_color=FG_MUTED,
            anchor="w",
        ).pack(anchor="w", padx=S_5, pady=(S_5, S_3))

    # ======================== 事件处理 ========================

    def _switch_mode(self, mode: Mode):
        if self.state.task_running:
            return
        self.state.mode = mode

        if mode == Mode.MASK:
            self._mode_mask_btn.configure(
                fg_color=PRIMARY, text_color=PRIMARY_FG,
                hover_color=PRIMARY_HOVER,
            )
            self._mode_restore_btn.configure(
                fg_color=BG_CARD, text_color=FG_MUTED,
                border_color=BORDER, border_width=1,
            )
            self._mode_hint.configure(text="脱敏：替换敏感信息，可使用同一密码本恢复")
            self._execute_btn.configure(text="预检并执行脱敏")
            self._report_cb.pack(anchor="w", padx=S_5, pady=(0, S_5))  # 显示覆盖率选项
        else:
            self._mode_mask_btn.configure(
                fg_color=BG_CARD, text_color=FG_MUTED,
                border_color=BORDER, border_width=1,
            )
            self._mode_restore_btn.configure(
                fg_color=PRIMARY, text_color=PRIMARY_FG,
                hover_color=PRIMARY_HOVER,
            )
            self._mode_hint.configure(text="恢复：使用同一密码本还原已脱敏的文档")
            self._execute_btn.configure(text="执行恢复")
            self._report_cb.pack_forget()  # 隐藏覆盖率选项

        self._update_execute_bar()

    def _on_codebook_change(self, path: str):
        if not path or not os.path.exists(path):
            self._update_codebook_status()
            return

        cb_state = self.controller.load_codebook(path)
        self.state.codebook = cb_state
        self._update_codebook_status()
        self._update_execute_bar()

    def _update_codebook_status(self):
        cb = self.state.codebook
        self._cb_warning.pack_forget()

        # 库密码本联动：在 PathPicker 中显示密码本名称
        if cb.is_loaded and cb.from_library and cb.library_name:
            current = self._codebook_picker.get_path()
            display = f"[库] {cb.library_name}"
            if current != display:
                self._codebook_picker.set_path(display)
        elif cb.is_loaded and not cb.from_library and cb.path:
            # 外部文件：确保 PathPicker 显示文件路径
            current = self._codebook_picker.get_path()
            if current != cb.path:
                self._codebook_picker.set_path(cb.path)

        if cb.error:
            self._cb_dot.configure(image=get_ctk_image("alert-triangle", 14, ERROR), text="")
            self._cb_status_text.configure(
                text=cb.error, text_color=ERROR,
            )
        elif not cb.is_loaded:
            self._cb_dot.configure(image=None, text="", text_color=FG_MUTED)
            self._cb_status_text.configure(
                text="请选择密码本", text_color=FG_MUTED,
            )
        elif cb.error_count > 0:
            self._cb_dot.configure(image=get_ctk_image("alert-triangle", 14, ERROR), text="")
            self._cb_status_text.configure(
                text=f"校验失败：发现 {cb.error_count} 个错误", text_color=ERROR,
            )
        elif cb.valid:
            self._cb_dot.configure(image=get_ctk_image("check-circle", 14, SUCCESS), text="")
            self._cb_status_text.configure(
                text=f"校验通过   {cb.exact_count} 条精确规则 · {cb.regex_count} 条正则规则",
                text_color=SUCCESS,
            )
            # 正则警告
            if cb.has_regex:
                self._cb_warning.pack(fill="x", padx=S_5, pady=(S_3, S_5))
            else:
                self._cb_warning.pack_forget()
        else:
            self._cb_dot.configure(image=get_ctk_image("alert-triangle", 14, WARNING), text="")
            self._cb_status_text.configure(
                text=f"校验通过（有 {cb.warning_count} 项警告）", text_color=WARNING,
            )

    def _on_filter_change(self):
        self.state.format_filters = {
            fmt for fmt, var in self._fmt_vars.items()
            if var.get() == "on"
        }
        self._save_settings()

    def _save_settings(self):
        """同步运行时状态到持久化设置并保存。"""
        self.state.settings.sync_from_state(self.state)
        self.state.settings.save()

    def _on_settings_changed(self):
        """设置页变更通知：同步工作台控件。"""
        # 同步格式过滤器
        for fmt, var in self._fmt_vars.items():
            var.set("on" if fmt in self.state.format_filters else "off")
        # 同步输出模式
        self._output_var.set("same_dir" if self.state.output_same_dir else "custom")
        self._output_picker.set_enabled(not self.state.output_same_dir)
        # 同步覆盖率报告
        self._report_var.set("on" if self.state.generate_report else "off")
        self._update_execute_bar()

    def _on_add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[
                ("支持的文档", "*.txt *.docx *.doc"),
                ("所有文件", "*.*"),
            ]
        )
        if paths:
            self.controller.add_files(list(paths))
            self._file_queue.refresh(self.state.files, self.state.task_running)
            self._update_execute_bar()

    def _on_add_folder(self):
        dir_path = filedialog.askdirectory()
        if dir_path:
            self._exec_info.configure(text="正在后台扫描目录...")
            self.controller.add_folder_async(
                dir_path,
                on_complete=self._on_folder_scan_complete,
                on_progress=lambda count, _path: self._exec_info.configure(
                    text=f"正在后台扫描目录... 已检查 {count} 个文件"
                ),
            )

    def _on_folder_scan_complete(self, added, skipped, errors):
        if errors:
            self._exec_info.configure(
                text=f"目录扫描完成：新增 {len(added)}，跳过 {skipped}，访问失败 {len(errors)}"
            )
        else:
            self._exec_info.configure(
                text=f"目录扫描完成：新增 {len(added)}，跳过 {skipped}"
            )
        if added or skipped or errors:
            self._file_queue.refresh(self.state.files, self.state.task_running)
            self._update_execute_bar()

    def _on_remove_file(self, index: int):
        if self.state.task_running:
            return
        self.controller.remove_file(index)
        self._file_queue.refresh(self.state.files, self.state.task_running)
        self._update_execute_bar()

    def _on_clear_files(self):
        if not self.state.files:
            return
        if self.state.task_running:
            return

        confirmed = show_confirm(
            self,
            title="清空文件队列",
            message=f"确定要移除全部 {self.state.file_count} 个文件吗？",
            confirm_text="清空",
            cancel_text="取消",
            danger=True,
        )
        if confirmed:
            self.controller.clear_files()
            self._file_queue.refresh(self.state.files)
            self._update_execute_bar()

    def _on_drop_files(self, paths: list[str]):
        """拖放文件/文件夹回调。

        A-14: 拖入目录统一走 add_folder_async 异步扫描，避免阻塞 UI。
        """
        if self.state.task_running:
            return
        file_paths = []
        dir_paths = []
        for p in paths:
            if os.path.isfile(p):
                file_paths.append(p)
            elif os.path.isdir(p):
                dir_paths.append(p)
        if file_paths:
            self.controller.add_files(file_paths)
            self._file_queue.refresh(self.state.files, self.state.task_running)
            self._update_execute_bar()
        if dir_paths:
            self._exec_info.configure(text="正在后台扫描目录...")
            for dir_path in dir_paths:
                self.controller.add_folder_async(
                    dir_path,
                    on_complete=self._on_folder_scan_complete,
                    on_progress=lambda count, _path: self._exec_info.configure(
                        text=f"正在后台扫描目录... 已检查 {count} 个文件"
                    ),
                )

    def _on_output_mode_change(self):
        is_custom = self._output_var.get() == "custom"
        self.state.output_same_dir = not is_custom
        self._output_picker.set_enabled(is_custom)
        self.state.output_dir = self._output_picker.get_path() or None if is_custom else None
        self._save_settings()
        self._update_execute_bar()

    def _on_output_dir_change(self, path: str):
        if not self.state.output_same_dir:
            self.state.output_dir = path.strip() or None
            self._save_settings()
            self._update_execute_bar()

    def _on_execute(self):
        # 同步输出目录
        if not self.state.output_same_dir:
            self.state.output_dir = self._output_picker.get_path() or None

        # 同步覆盖率报告
        self.state.generate_report = self._report_var.get() == "on"
        self._save_settings()

        if not self.state.can_execute:
            self._update_execute_bar()
            return

        # 启动后台任务，Controller 成功启动后再切换界面状态。
        started = self.controller.execute(
            on_file_start=self._on_file_start,
            on_file_done=self._on_file_done,
            on_progress=self._on_progress,
            on_complete=self._on_complete,
        )
        if started:
            self._set_running_ui(True)

    def _on_stop(self):
        confirmed = show_confirm(
            self,
            title="停止任务",
            message="确定要停止当前任务吗？已完成的文件不会被删除。",
            confirm_text="停止",
            cancel_text="继续",
            danger=True,
        )
        if confirmed:
            self.controller.cancel()

    # ======================== 任务回调（主线程） ========================

    def _on_file_start(self, index: int, item: FileItem):
        self._file_queue.update_row(index, item)

    def _on_file_done(self, index: int, item: FileItem):
        self._file_queue.update_row(index, item)

    def _on_progress(self, current: int, total: int, message: str):
        self._exec_info.configure(text=message)
        if total > 0:
            self._progress_bar.set(current / total)

    def _on_complete(self, results: list[FileItem]):
        self._set_running_ui(False)
        self._file_queue.refresh(self.state.files)

        # 检查是否有冲突
        conflicts = [
            (item.filename, item.conflict_details)
            for item in results
            if item.status == FileStatus.CONFLICT and item.conflict_details
        ]
        if conflicts:
            ConflictDialog(self, conflicts)

        # 跳转到结果页
        if self.on_navigate:
            self.on_navigate("results")

    # ======================== UI 状态 ========================

    def _set_running_ui(self, running: bool):
        """切换执行中/就绪 UI 状态"""
        if running:
            self._execute_btn.pack_forget()
            self._stop_btn.pack(side="right")
            self._mode_mask_btn.configure(state="disabled")
            self._mode_restore_btn.configure(state="disabled")
            self._codebook_picker.set_enabled(False)
            self._progress_bar.pack(fill="x", pady=(S_2, 0))
            self._progress_bar.set(0)
            self._status_label.configure(
                text="处理中", image=get_ctk_image("refresh", 16, INFO), text_color=INFO,
            )
            self._file_queue.set_task_running(True)
        else:
            self._stop_btn.pack_forget()
            self._execute_btn.pack(side="right")
            self._mode_mask_btn.configure(state="normal")
            self._mode_restore_btn.configure(state="normal")
            self._codebook_picker.set_enabled(True)
            self._progress_bar.pack_forget()
            self._status_label.configure(
                text="就绪", image=get_ctk_image("check-circle", 16, SUCCESS), text_color=SUCCESS,
            )
            self._file_queue.set_task_running(False)

        self._update_execute_bar()

    def _update_execute_bar(self):
        """更新执行栏信息"""
        file_count = self.state.file_count
        cb_valid = self.state.codebook.valid

        parts = [f"{file_count} 个文件待处理"]
        if cb_valid:
            parts.append("密码本已通过校验")
        elif self.state.codebook.is_loaded:
            parts.append("密码本校验未通过")
        if not self.state.output_dir_valid:
            parts.append("请选择有效的输出目录")

        self._exec_info.configure(text="  |  ".join(parts))

        # 执行按钮状态
        can_exec = self.state.can_execute
        self._execute_btn.configure(
            state="normal" if can_exec else "disabled",
        )

    def on_show(self):
        """页面被显示时调用"""
        # 同步设置页可能修改的控件状态
        for fmt, var in self._fmt_vars.items():
            var.set("on" if fmt in self.state.format_filters else "off")
        self._output_var.set("same_dir" if self.state.output_same_dir else "custom")
        self._output_picker.set_enabled(not self.state.output_same_dir)
        self._report_var.set("on" if self.state.generate_report else "off")

        self._update_codebook_status()
        self._file_queue.refresh(self.state.files, self.state.task_running)
        self._update_execute_bar()
