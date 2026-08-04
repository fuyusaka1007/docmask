"""UI 诊断工具：纯内存环形缓冲，退出时一次性写入文件。

不调用网络、不阻塞主线程、不依赖外部服务。
"""
from __future__ import annotations

import json
import time
import threading
from collections import deque
from pathlib import Path
from typing import Any


class RingBuffer:
    """线程安全的环形缓冲。"""

    def __init__(self, capacity: int = 4096):
        self._capacity = capacity
        self._buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        entry["ts"] = time.time_ns()
        with self._lock:
            self._buffer.append(entry)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


class ScrollDiagnostics:
    """滚动诊断：记录鼠标滚轮事件和滚动容器状态。"""

    _instance: "ScrollDiagnostics | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "ScrollDiagnostics":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._buffer = RingBuffer(capacity=4096)
            return cls._instance

    @property
    def buffer(self) -> RingBuffer:
        return self._buffer

    def record(self, **fields) -> None:
        """记录一条滚动诊断事件。"""
        self._buffer.append(fields)

    def export(self, path: Path) -> None:
        """将当前缓冲导出为 NDJSON。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self._buffer.snapshot()
        with open(path, "w", encoding="utf-8") as f:
            for entry in snapshot:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# 全局访问点
scroll_diag = ScrollDiagnostics()
