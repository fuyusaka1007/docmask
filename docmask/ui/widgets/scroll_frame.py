"""自定义滚动容器，替代 CTkScrollableFrame。

CTkScrollableFrame 每个实例都调用 bind_all("<MouseWheel>", ..., add=True)，
多实例时事件冲突。本模块使用全局单例路由器，只注册一次鼠标滚轮事件，
按控件祖先链路由到正确的滚动容器。
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
import customtkinter as ctk

from docmask.ui.diagnostics import scroll_diag

# 合并窗口（毫秒）：macOS 触摸板 60-120Hz，16ms ≈ 一帧
_COALESCE_MS = 16

# 边界 epsilon：防止浮点精度导致 0.9999↔1.0 反复触发边界
_BOUNDARY_EPS = 0.001

# 边界锁：到达边界后，在此时长内抑制反方向小 delta（毫秒）
_BOUNDARY_LOCK_MS = 200

# 边界锁期间，反方向 delta 低于此值被抑制
_BOUNDARY_LOCK_THRESHOLD = 3


class PageScrollFrame(ctk.CTkFrame):
    """基于 Canvas 的滚动容器。

    与 CTkScrollableFrame 的关键区别：
    - 全局只注册一次 <MouseWheel> 事件（而非每个实例都 bind_all）
    - 按控件祖先链路由到正确的滚动容器
    - 到达顶部/底部时不向父级传播
    - 使用 after(16) 合并窗口而非 after_idle，防止 macOS 高频事件逐条处理
    """

    _wheel_bound = False

    def __init__(self, master, **kwargs):
        # 兼容 CTkScrollableFrame 的滚动条参数
        kwargs.pop("scrollbar_button_color", None)
        kwargs.pop("scrollbar_button_hover_color", None)

        super().__init__(master, **kwargs)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        # Canvas
        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            background=self._resolve_bg(),
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        # 滚动条
        self._scrollbar = ctk.CTkScrollbar(
            self,
            orientation="vertical",
            command=self._canvas.yview,
        )
        self._scrollbar.grid(row=0, column=1, sticky="ns")

        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        # 内容容器
        self._content = ctk.CTkFrame(self._canvas, fg_color="transparent")
        self._canvas.create_window(
            (0, 0), window=self._content, anchor="nw", tags=("content",),
        )

        # 内容变化时更新滚动区域
        self._content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # 上次记录的内容宽高，用于检测实际变化
        self._last_content_width = 0
        self._last_content_height = 0

        # 合并滚动状态
        self._pending_delta = 0.0
        self._scroll_job: str | None = None

        # 边界锁状态：0=无, +1=底部锁(抑制上滑), -1=顶部锁(抑制下滑)
        self._boundary_lock_dir = 0
        self._boundary_lock_until = 0.0

        # 全局滚轮路由（只注册一次）
        self.__class__._bind_wheel_global()

    @property
    def content(self) -> ctk.CTkFrame:
        """内部内容容器，子控件 pack/grid 到这里。"""
        return self._content

    # ---- 外观模式 ----

    def _resolve_bg(self) -> str:
        """将 fg_color 解析为 Canvas 可用的颜色字符串。"""
        try:
            fg = self.cget("fg_color")
        except Exception:
            fg = "transparent"
        if fg == "transparent":
            fg = ("gray92", "gray14")
        return self._apply_appearance_mode(fg)

    def _set_appearance_mode(self, mode_string):
        """外观模式变化时同步 Canvas 背景。"""
        super()._set_appearance_mode(mode_string)
        try:
            self._canvas.configure(background=self._resolve_bg())
        except Exception:
            pass

    # ---- 滚动区域管理 ----

    def _on_content_configure(self, event):
        """内容尺寸变化时更新滚动区域。

        只在内容高度实际变化时更新 scrollregion，
        避免滚动过程中频繁触发 yview 重算。
        """
        h = event.height
        if h == self._last_content_height:
            return
        old_h = self._last_content_height
        self._last_content_height = h
        y_before = list(self._canvas.yview())
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        y_after = list(self._canvas.yview())
        scroll_diag.record(
            source="content_configure",
            old_height=old_h,
            new_height=h,
            y_before=y_before,
            y_after=y_after,
            frame_id=id(self),
        )

    def _on_canvas_configure(self, event):
        """Canvas 尺寸变化时同步内容宽度。

        只在宽度实际变化时更新，避免反馈环：
        宽度变 -> 文本重排 -> 高度变 -> scrollregion 变 -> yview 跳。
        """
        w = event.width
        if w == self._last_content_width:
            return
        old_w = self._last_content_width
        self._last_content_width = w
        y_before = list(self._canvas.yview())
        self._canvas.itemconfigure("content", width=w)
        y_after = list(self._canvas.yview())
        scroll_diag.record(
            source="canvas_configure",
            old_width=old_w,
            new_width=w,
            y_before=y_before,
            y_after=y_after,
            frame_id=id(self),
        )

    # ---- 全局滚轮路由 ----

    @classmethod
    def _bind_wheel_global(cls):
        """全局只注册一次鼠标滚轮事件。

        使用 add="" 替换而非追加，防止 CustomTkinter 或其他组件
        的 <MouseWheel> 绑定同时触发造成方向冲突。
        """
        if cls._wheel_bound:
            return
        root = tk._default_root
        if root is not None:
            root.bind_all("<MouseWheel>", cls._on_mouse_wheel, add="")
            root.bind_all("<Button-4>", cls._on_button_45, add="+")
            root.bind_all("<Button-5>", cls._on_button_45, add="+")
            cls._wheel_bound = True

    @classmethod
    def _find_frame(cls, widget) -> "PageScrollFrame | None":
        """沿父级链查找最近的 PageScrollFrame。"""
        w = widget
        while w is not None:
            if isinstance(w, cls):
                return w
            try:
                w = w.master
            except Exception:
                return None
        return None

    @classmethod
    def _on_mouse_wheel(cls, event):
        """macOS / Windows 鼠标滚轮事件。"""
        try:
            frame = cls._find_frame(event.widget)
            if frame is None or not frame.winfo_ismapped():
                return
        except Exception:
            return
        if sys.platform == "darwin":
            delta = -event.delta
        else:
            delta = -event.delta / 120.0
        frame._scroll(delta, source="mouse_wheel",
                      widget_class=type(event.widget).__name__)

    @classmethod
    def _on_button_45(cls, event):
        """Linux 滚轮事件。"""
        try:
            frame = cls._find_frame(event.widget)
            if frame is None or not frame.winfo_ismapped():
                return
        except Exception:
            return
        direction = -1 if event.num == 4 else 1
        frame._scroll(direction * 3, source="button_45",
                      widget_class=type(event.widget).__name__)

    # ---- 滚动逻辑 ----

    def _scroll(self, delta: float, source: str = "unknown",
                widget_class: str = ""):
        """累积滚动增量，在合并窗口结束后统一应用。

        macOS 触摸板以 60-120Hz 发送小 delta 事件。
        after_idle 在事件间隙立即触发，无法有效合并。
        改用 after(16) 创建一帧的合并窗口，确保同一方向的事件
        被合并为一次滚动，避免惯性末端的反向事件单独执行。
        """
        if delta == 0:
            return

        self._pending_delta += delta

        # 诊断记录（纯内存，不阻塞）
        scroll_diag.record(
            platform=sys.platform,
            source=source,
            widget_class=widget_class,
            raw_delta=delta,
            pending_delta=self._pending_delta,
            y_before=list(self._canvas.yview()),
            scrollregion=list(self._canvas.bbox("all") or (0, 0, 0, 0)),
            canvas_size=(self._canvas.winfo_width(),
                         self._canvas.winfo_height()),
            mapped=self.winfo_ismapped(),
            frame_id=id(self),
        )

        # 已有待执行的合并回调时，只累积 delta，不重新调度
        if self._scroll_job is None:
            self._scroll_job = self.after(_COALESCE_MS,
                                          self._apply_pending_scroll)

    def _apply_pending_scroll(self):
        """合并窗口结束后，统一应用累积的滚动增量。"""
        self._scroll_job = None
        delta = self._pending_delta
        self._pending_delta = 0.0

        if abs(delta) < 0.01:
            return

        units = int(round(delta))
        if units == 0:
            # delta 太小但非零，保留方向
            units = 1 if delta > 0 else -1

        now = time.monotonic()
        lock_active = self._boundary_lock_dir != 0 and now < self._boundary_lock_until

        # 边界锁：抑制反方向小 delta（触摸板动量噪声）
        if lock_active:
            if self._boundary_lock_dir > 0 and units < 0 and abs(units) < _BOUNDARY_LOCK_THRESHOLD:
                scroll_diag.record(
                    source="boundary_lock_suppressed",
                    boundary="bottom", suppressed_units=units,
                    frame_id=id(self),
                )
                return
            if self._boundary_lock_dir < 0 and units > 0 and abs(units) < _BOUNDARY_LOCK_THRESHOLD:
                scroll_diag.record(
                    source="boundary_lock_suppressed",
                    boundary="top", suppressed_units=units,
                    frame_id=id(self),
                )
                return
        elif self._boundary_lock_dir != 0:
            # 锁已过期
            self._boundary_lock_dir = 0

        top, bottom = self._canvas.yview()

        # 边界检查（带 epsilon 防止浮点精度反复触发）
        if units < 0 and top <= _BOUNDARY_EPS:
            self._boundary_lock_dir = -1
            self._boundary_lock_until = now + _BOUNDARY_LOCK_MS / 1000.0
            scroll_diag.record(
                source="boundary", boundary="top",
                attempted_units=units, y_view=(top, bottom),
                frame_id=id(self),
            )
            return
        if units > 0 and bottom >= 1 - _BOUNDARY_EPS:
            self._boundary_lock_dir = 1
            self._boundary_lock_until = now + _BOUNDARY_LOCK_MS / 1000.0
            scroll_diag.record(
                source="boundary", boundary="bottom",
                attempted_units=units, y_view=(top, bottom),
                frame_id=id(self),
            )
            return

        self._canvas.yview_scroll(units, "units")

        scroll_diag.record(
            source="applied",
            applied_units=units,
            y_after=list(self._canvas.yview()),
            frame_id=id(self),
        )
