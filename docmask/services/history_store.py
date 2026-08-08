"""工作历史存储：追加式 JSONL，记录每次脱敏/恢复操作

所有数据存储在 user_data_dir()/history.jsonl，纯本地，不上传。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from docmask.utils.file_utils import user_data_dir


@dataclass
class HistoryEntry:
    """工作历史单条记录"""
    timestamp: str
    mode: str               # "mask" | "restore"
    input_path: str
    input_filename: str
    output_path: str
    codebook_name: str
    codebook_version: str
    exact_rule_count: int
    regex_rule_count: int
    replacements: int
    status: str             # "done" | "conflict" | "failed" | "stopped"
    error: Optional[str] = None


class HistoryStore:
    """工作历史存储（追加式 JSONL）"""

    MAX_ENTRIES = 1000

    def __init__(self, path: Optional[Path] = None):
        self._path = path or (user_data_dir() / "history.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: HistoryEntry) -> None:
        """追加一条记录。若总条数超过 MAX_ENTRIES，删除最旧的。"""
        line = json.dumps(asdict(entry), ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

        # 超过上限时从头删除
        if self.count() > self.MAX_ENTRIES:
            self._trim_to_max()

    def query(self, limit: int = 100, offset: int = 0) -> list[HistoryEntry]:
        """查询历史记录（按时间倒序，跳过 offset 条，返回最近 limit 条）。"""
        entries = self._read_all()
        entries.reverse()  # 倒序（最近在前）
        sliced = entries[offset: offset + limit]
        return sliced

    def count(self) -> int:
        """返回总记录数。"""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    def clear(self) -> None:
        """清空所有历史记录。"""
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    def _read_all(self) -> list[HistoryEntry]:
        """读取全部记录（正序）。"""
        if not self._path.exists():
            return []
        entries = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(HistoryEntry(
                        timestamp=data["timestamp"],
                        mode=data["mode"],
                        input_path=data["input_path"],
                        input_filename=data["input_filename"],
                        output_path=data["output_path"],
                        codebook_name=data["codebook_name"],
                        codebook_version=data["codebook_version"],
                        exact_rule_count=data["exact_rule_count"],
                        regex_rule_count=data["regex_rule_count"],
                        replacements=data["replacements"],
                        status=data["status"],
                        error=data.get("error"),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
        return entries

    def _trim_to_max(self) -> None:
        """删除最旧的记录，保留最近 MAX_ENTRIES 条。"""
        entries = self._read_all()
        if len(entries) <= self.MAX_ENTRIES:
            return
        keep = entries[len(entries) - self.MAX_ENTRIES:]
        # 原子重写
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".history.", suffix=".tmp", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                for entry in keep:
                    f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self._path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
