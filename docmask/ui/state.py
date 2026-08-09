"""UI 应用状态：模式、密码本、文件队列、任务结果"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from docmask.core.codebook import Codebook
from docmask.config import DEFAULT_FORMATS
from docmask.utils.file_utils import user_data_dir

logger = logging.getLogger(__name__)


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

    # beta3: 密码本库相关
    library_id: Optional[str] = None
    library_name: Optional[str] = None
    version: Optional[str] = None
    from_library: bool = False
    edit_rules: list = field(default_factory=list)

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


@dataclass(frozen=True)
class TaskContext:
    """A-12: 任务执行上下文的不可变快照。

    在任务开始时创建，整个任务执行期间使用此快照，
    避免 UI 修改全局状态影响正在运行的任务。
    """
    mode: Mode
    codebook: Codebook
    codebook_name: str
    codebook_version: str
    exact_count: int
    regex_count: int
    output_same_dir: bool
    output_dir: Optional[str]
    generate_report: bool
    history_enabled: bool


@dataclass
class SettingsModel:
    """持久化用户偏好设置，保存到用户数据目录的 settings.json。"""

    theme: str = "跟随系统"  # 深色 / 浅色 / 跟随系统
    scale: str = "100%"  # 界面缩放
    log_level: str = "INFO"  # 日志级别
    format_filters: list[str] = field(default_factory=lambda: ["docx", "doc", "txt"])
    output_same_dir: bool = True
    generate_report: bool = True
    record_history: bool = True  # beta3: 工作历史记录开关

    # A-05: 值类型校验白名单
    _VALID_THEMES = {"深色", "浅色", "跟随系统"}
    _VALID_SCALES = {"80%", "90%", "100%", "110%", "120%"}
    _VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    _VALID_FORMATS = set(DEFAULT_FORMATS)

    @classmethod
    def load(cls) -> "SettingsModel":
        """从用户数据目录加载设置；文件不存在或损坏时返回默认值。

        A-05: 按字段校验值类型，坏字段回退默认值并记录 warning，
        不因单个坏字段丢弃全部有效设置。
        """
        path = cls._settings_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("settings.json 解析失败，使用默认设置")
            return cls()
        if not isinstance(data, dict):
            logger.warning("settings.json 顶层不是对象，使用默认设置")
            return cls()

        # 按字段校验，坏字段回退默认值
        defaults = cls()
        theme = cls._validate_str(data, "theme", cls._VALID_THEMES, defaults.theme)
        scale = cls._validate_str(data, "scale", cls._VALID_SCALES, defaults.scale)
        log_level = cls._validate_str(data, "log_level", cls._VALID_LOG_LEVELS, defaults.log_level)
        format_filters = cls._validate_format_filters(data, defaults.format_filters)
        output_same_dir = cls._validate_bool(data, "output_same_dir", defaults.output_same_dir)
        generate_report = cls._validate_bool(data, "generate_report", defaults.generate_report)
        record_history = cls._validate_bool(data, "record_history", defaults.record_history)
        return cls(
            theme=theme,
            scale=scale,
            log_level=log_level,
            format_filters=format_filters,
            output_same_dir=output_same_dir,
            generate_report=generate_report,
            record_history=record_history,
        )

    @staticmethod
    def _validate_str(data: dict, key: str, allowed: set[str], default: str) -> str:
        value = data.get(key, default)
        if isinstance(value, str) and value in allowed:
            return value
        logger.warning("settings.json 字段 %s 值无效，回退默认值", key)
        return default

    @staticmethod
    def _validate_bool(data: dict, key: str, default: bool) -> bool:
        value = data.get(key, default)
        if isinstance(value, bool):
            return value
        logger.warning("settings.json 字段 %s 值无效，回退默认值", key)
        return default

    @classmethod
    def _validate_format_filters(cls, data: dict, default: list[str]) -> list[str]:
        value = data.get("format_filters", default)
        if not isinstance(value, list):
            logger.warning("settings.json 字段 format_filters 值无效，回退默认值")
            return default
        valid = [f for f in value if isinstance(f, str) and f in cls._VALID_FORMATS]
        if not valid:
            logger.warning("settings.json 字段 format_filters 无有效项，回退默认值")
            return default
        return valid

    def save(self) -> None:
        """保存设置到用户数据目录。

        A-05: 使用同目录临时文件 + 原子提交，不完全吞掉异常。
        """
        path = self._settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(asdict(self), ensure_ascii=False, indent=2)
            # 同目录临时文件 + 原子重命名
            fd, temp_name = tempfile.mkstemp(
                prefix=".settings.", suffix=".tmp", dir=str(path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(temp_name, path)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        except Exception:
            logger.warning("保存 settings.json 失败", exc_info=True)

    @staticmethod
    def _settings_path() -> Path:
        return user_data_dir() / "settings.json"

    def apply_to_state(self, state: "AppState") -> None:
        """将设置应用到运行时 AppState。"""
        state.format_filters = set(self.format_filters)
        state.output_same_dir = self.output_same_dir
        state.generate_report = self.generate_report
        state.history_enabled = self.record_history

    def sync_from_state(self, state: "AppState") -> None:
        """从运行时 AppState 同步设置。"""
        self.format_filters = sorted(state.format_filters)
        self.output_same_dir = state.output_same_dir
        self.generate_report = state.generate_report
        self.record_history = state.history_enabled


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
    history_enabled: bool = True  # beta3: 工作历史记录开关

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
