"""DocMask 应用入口：主窗口、侧边导航、页面切换、主题"""
from __future__ import annotations

import logging
import time

import customtkinter as ctk

from docmask.ui.theme import (
    font, FS_BODY,
    WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    SIDEBAR_WIDTH, BG_PAGE,
)
from docmask.ui.state import AppState, SettingsModel
from docmask.ui.controller import TaskController
from docmask.ui.widgets.sidebar import Sidebar
from docmask.ui.widgets.dialogs import show_confirm
from docmask.ui.pages.workbench_page import WorkbenchPage
from docmask.ui.pages.codebook_page import CodebookPage
from docmask.ui.pages.results_page import ResultsPage
from docmask.ui.pages.settings_page import SettingsPage
from docmask.ui.diagnostics import scroll_diag
from docmask.utils.file_utils import user_data_dir
from docmask.utils.logger import setup_logging

# 拖放支持（可选，需要 tkinterdnd2）
try:
    from tkinterdnd2 import TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

logger = logging.getLogger(__name__)

# 主题映射
_THEME_MAP = {"深色": "Dark", "浅色": "Light", "跟随系统": "System"}


class DocMaskApp(ctk.CTk):
    """DocMask 主应用"""

    def __init__(self):
        super().__init__()

        # 加载持久化设置
        self._settings = SettingsModel.load()

        # 初始化日志系统
        setup_logging(self._settings.log_level, console=False)
        logger.info("DocMask 应用启动")

        # 窗口设置
        self.title("DocMask - 文档脱敏工具")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # 主题和缩放（从设置加载）
        ctk.set_appearance_mode(_THEME_MAP.get(self._settings.theme, "System"))
        ctk.set_default_color_theme("blue")
        scale_str = self._settings.scale.replace("%", "")
        try:
            scale = int(scale_str) / 100.0
            if 0.5 <= scale <= 3.0:
                ctk.set_widget_scaling(scale)
        except (ValueError, TypeError):
            pass

        # 状态和控制器（注意：不能用 self.state，会覆盖 Tk 的 state() 方法）
        self.app_state = AppState()
        self.app_state.settings = self._settings
        self._settings.apply_to_state(self.app_state)
        self.controller = TaskController(self.app_state, self)

        # 初始化拖放支持
        self.dnd_available = False
        if _DND_AVAILABLE:
            try:
                TkinterDnD._require(self)
                self.dnd_available = True
            except Exception as e:
                logger.debug("tkdnd 初始化失败: %s", e)

        # 页面：只在首次访问时构建，避免 macOS CustomTkinter 同时初始化多个滚动容器。
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._page_factories = {
            "workbench": lambda: WorkbenchPage(
                self._content_frame, self.app_state, self.controller,
                on_navigate=self._show_page,
            ),
            "codebook": lambda: CodebookPage(
                self._content_frame, self.app_state, self.controller,
            ),
            "results": lambda: ResultsPage(
                self._content_frame, self.app_state, self.controller,
            ),
            "settings": lambda: SettingsPage(
                self._content_frame, self.app_state, self.controller,
                on_settings_change=self._on_settings_change,
            ),
        }
        self._current_page: str | None = None

        # 布局
        self._build_sidebar()
        self._build_content()

        # 显示默认页面
        self._show_page("workbench")

        # 窗口关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_settings_change(self, settings: SettingsModel):
        """设置页面变更通知：应用主题/缩放/日志级别，并通知其他页面。"""
        self._settings = settings
        ctk.set_appearance_mode(_THEME_MAP.get(settings.theme, "System"))
        scale_str = settings.scale.replace("%", "")
        try:
            scale = int(scale_str) / 100.0
            if 0.5 <= scale <= 3.0:
                ctk.set_widget_scaling(scale)
        except (ValueError, TypeError):
            pass
        # 通知所有已创建的页面
        self.app_state.notify_change()

    def _build_sidebar(self):
        self._sidebar = Sidebar(self, on_navigate=self._show_page)
        self._sidebar.pack(side="left", fill="y")

    def _build_content(self):
        self._content_frame = ctk.CTkFrame(
            self, fg_color=BG_PAGE, corner_radius=0,
        )
        self._content_frame.pack(side="left", fill="both", expand=True)

    def _show_page(self, page_id: str):
        """切换页面"""
        if page_id == self._current_page:
            return

        # 隐藏当前页面
        if self._current_page in self._pages:
            self._pages[self._current_page].pack_forget()

        # 显示新页面
        if page_id not in self._pages and page_id in self._page_factories:
            self._pages[page_id] = self._page_factories[page_id]()
        if page_id in self._pages:
            page = self._pages[page_id]
            page.pack(fill="both", expand=True)
            # 调用 on_show 回调
            if hasattr(page, "on_show"):
                page.on_show()

        self._current_page = page_id
        self._sidebar.set_active(page_id)

    def _on_close(self):
        """窗口关闭事件"""
        if self.app_state.task_running:
            confirmed = show_confirm(
                self,
                title="任务仍在进行",
                message="任务仍在进行，关闭窗口将停止处理。\n确定要关闭吗？",
                confirm_text="关闭并停止",
                cancel_text="继续任务",
                danger=True,
            )
            if not confirmed:
                return
        self.controller.shutdown(timeout=2.0)
        # 保存设置
        self._settings.sync_from_state(self.app_state)
        self._settings.save()
        self._export_scroll_diagnostics()
        self.destroy()

    def _export_scroll_diagnostics(self):
        """退出时将滚动诊断缓冲写入本地文件（纯内存，不阻塞）。"""
        try:
            if len(scroll_diag.buffer) == 0:
                return
            diag_dir = user_data_dir() / "diagnostics"
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            diag_path = diag_dir / f"scroll-diagnostics-{timestamp}.jsonl"
            scroll_diag.export(diag_path)
        except Exception:
            # 诊断导出失败不应阻止应用退出
            pass


def launch():
    """启动 DocMask GUI 应用"""
    app = DocMaskApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
