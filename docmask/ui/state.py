"""UI 应用状态：模式、密码本、文件队列、任务结果"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from docmask.core.codebook import Codebook
from docmask.utils.file_utils import user_data_dir


class Mode(str, Enum):
    MASK = "mask"
    RESTORE = "restore"


class FileStatus(str, Enum):
    WAITING = "等待预检"
    PROCESSING = "处理中"
    DONE = "完成"
    CONFLICT = "冲突"
    FAILED = "失败"
    STOPPED = "已停止"


@dataclass
class FileItem:
    """文件队列项"""
    path: str
    filename: str
    fmt: str          # docx / doc / txt / other
    size: int         # bytes
    status: FileStatus = FileStatus.WAITING
    output_path: Optional[str] = None
    replacements: int = 0
    error_message: Optional[str] = None
    conflict_details: Optional[str] = None
    coverage: Optional[dict] = None  # 覆盖率报告数据（仅脱敏）
    warnings: list[str] = field(default_factory=list)

    @property
    def size_str(self) -> str:
        """格式化文件大小"""
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        else:
            return f"{self.size / (1024 * 1024):.1f} MB"


@dataclass
class CodebookState:
    """密码本状态"""
    path: Optional[str] = None
    codebook: Optional[Codebook] = None
    valid: bool = False
    error_count: int = 0
    warning_count: int = 0
    messages: list[str] = field(default_factory=list)
    error: Optional[str] = None  # 加载异常

    @property
    def is_loaded(self) -> bool:
        return self.codebook is not None

    @property
    def exact_count(self) -> int:
        if self.codebook:
            return self.codebook.exact_rule_count
        return 0

    @property
    def regex_count(self) -> int:
        if self.codebook:
            return self.codebook.regex_rule_count
        return 0

    @property
    def has_regex(self) -> bool:
        return self.regex_count > 0


@dataclass
class SettingsModel:
    """持久化用户偏好设置，保存到用户数据目录的 settings.json。"""

    theme: str = "跟随系统"  # 深色 / 浅色 / 跟随系统
    scale: str = "100%"  # 界面缩放
    log_level: str = "INFO"  # 日志级别
    format_filters: list[str] = field(default_factory=lambda: ["docx", "doc", "txt"])
    output_same_dir: bool = True
    generate_report: bool = True

    @classmethod
    def load(cls) -> "SettingsModel":
        """从用户数据目录加载设置；文件不存在或损坏时返回默认值。"""
        path = cls._settings_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                valid_keys = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**valid_keys)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        """保存设置到用户数据目录。"""
        path = self._settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _settings_path() -> Path:
        return user_data_dir() / "settings.json"

    def apply_to_state(self, state: "AppState") -> None:
        """将设置应用到运行时 AppState。"""
        state.format_filters = set(self.format_filters)
        state.output_same_dir = self.output_same_dir
        state.generate_report = self.generate_report

    def sync_from_state(self, state: "AppState") -> None:
        """从运行时 AppState 同步设置。"""
        self.format_filters = sorted(state.format_filters)
        self.output_same_dir = state.output_same_dir
        self.generate_report = state.generate_report


@dataclass
class AppState:
    """全局应用状态"""
    mode: Mode = Mode.MASK
    codebook: CodebookState = field(default_factory=CodebookState)
    files: list[FileItem] = field(default_factory=list)
    format_filters: set[str] = field(default_factory=lambda: {"docx", "doc", "txt"})

    # 输出设置
    output_same_dir: bool = True
    output_dir: Optional[str] = None
    generate_report: bool = True

    # 持久化设置
    settings: SettingsModel = field(default_factory=SettingsModel)

    # 任务状态
    task_running: bool = False
    task_progress_current: int = 0
    task_progress_total: int = 0
    task_message: str = ""

    # 设置变更监听器（不参与比较/序列化）
    _listeners: list[Callable[[], None]] = field(
        default_factory=list, repr=False, compare=False
    )

    def add_listener(self, callback: Callable[[], None]) -> None:
        """注册设置变更监听器。"""
        self._listeners.append(callback)

    def notify_change(self) -> None:
        """通知所有监听器设置已变更。"""
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                pass

    @property
    def can_execute(self) -> bool:
        """是否满足执行条件"""
        return (
            self.codebook.valid
            and len(self.files) > 0
            and not self.task_running
            and self.output_dir_valid
        )

    @property
    def output_dir_valid(self) -> bool:
        """同目录模式恒为有效；自定义模式必须选择已存在的目录。"""
        return self.output_same_dir or bool(
            self.output_dir and os.path.isdir(self.output_dir)
        )

    @property
    def file_count(self) -> int:
        return len(self.files)

    def reset_file_status(self) -> None:
        """重置所有文件状态为等待预检"""
        for f in self.files:
            f.status = FileStatus.WAITING
            f.output_path = None
            f.replacements = 0
            f.error_message = None
            f.conflict_details = None
            f.coverage = None
            f.warnings.clear()


def create_file_item(path: str) -> FileItem:
    """从路径创建 FileItem"""
    filename = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    fmt = ext if ext in ("docx", "doc", "txt") else "other"
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return FileItem(path=path, filename=filename, fmt=fmt, size=size)
