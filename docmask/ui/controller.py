"""Controller：连接 UI 与 core/handlers，管理后台任务

所有文件处理在后台线程执行；工作线程只写入 Queue，Tk 调用仅发生在主线程。
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from docmask.core.codebook import Codebook, CodebookError, CodebookRule
from docmask.core.masker import Masker, MaskConflictError
from docmask.core.restorer import Restorer
from docmask.handlers.base import CancelToken, TaskCancelledError
from docmask.services.file_service import scan_files, get_handler
from docmask.services.codebook_library import CodebookLibrary, CodebookMeta, VersionInfo
from docmask.services.history_store import HistoryStore, HistoryEntry
from docmask.utils.file_utils import generate_output_path
from docmask.config import DESENSITIZED_SUFFIX, RESTORED_SUFFIX

from docmask.ui.state import (
    AppState, CodebookState, FileItem, FileStatus, Mode, TaskContext,
    create_file_item,
)

logger = logging.getLogger(__name__)

# UI 回调类型
FileCallback = Callable[[int, FileItem], None]
ProgressCallback = Callable[[int, int, str], None]
TaskCompleteCallback = Callable[[list[FileItem]], None]


class TaskController:
    """任务控制器：管理密码本加载、文件队列和后台执行"""

    def __init__(self, state: AppState, tk_root):
        self.state = state
        self.tk_root = tk_root
        self._thread: Optional[threading.Thread] = None
        self._cancel_token: Optional[CancelToken] = None
        self._event_queue: queue.Queue[tuple[Callable, tuple]] = queue.Queue()
        self._event_polling = False
        self._closed = False
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_cancel = threading.Event()
        self._library: Optional[CodebookLibrary] = None
        self._history: Optional[HistoryStore] = None
        self._task_context: Optional[TaskContext] = None

    # ======================== 密码本库 ========================

    def init_library(self) -> CodebookLibrary:
        """初始化密码本库（懒加载）。"""
        if self._library is None:
            self._library = CodebookLibrary()
        return self._library

    def list_codebooks(self) -> list[CodebookMeta]:
        return self.init_library().list_codebooks()

    def create_codebook(self, name: str, description: str = "") -> CodebookMeta:
        return self.init_library().create(name, description)

    def load_library_codebook(self, codebook_id: str) -> CodebookState:
        """从库加载密码本到当前状态。"""
        lib = self.init_library()
        cb = lib.load(codebook_id)
        meta = None
        for m in lib.list_codebooks():
            if m.id == codebook_id:
                meta = m
                break
        messages = cb.validate()
        error_count = sum(1 for m in messages if m.startswith("ERROR"))
        warning_count = sum(1 for m in messages if m.startswith("WARNING"))
        cb_state = CodebookState(
            path=str(lib._current_path(codebook_id)),
            codebook=cb,
            valid=error_count == 0,
            error_count=error_count,
            warning_count=warning_count,
            messages=messages,
            library_id=codebook_id,
            library_name=meta.name if meta else "",
            version=meta.current_version if meta else "",
            from_library=True,
            edit_rules=cb.to_rules() if cb.exact_rule_count or cb.regex_rule_count else [],
        )
        self.state.codebook = cb_state
        return cb_state

    def save_codebook_to_library(
        self, codebook_id: str, rules: list[CodebookRule]
    ) -> tuple[Optional[VersionInfo], list[str]]:
        """保存密码本到库（生成新版本快照）。

        A-02: 含 ERROR 的密码本禁止保存，返回 (None, messages)。
        """
        lib = self.init_library()
        cb = Codebook.__new__(Codebook)
        cb.filepath = ""
        cb.forward_map = {}
        cb.reverse_map = {}
        cb._sorted_keys = []
        cb.regex_rules = []
        cb._line_numbers = {}
        cb._regex_line_numbers = []
        cb._raw_content = ""
        messages = cb.update_rules(rules)
        # A-02: 存在 ERROR 时不保存，防止无效密码本覆盖当前版本
        has_error = any(m.startswith("ERROR") for m in messages)
        if has_error:
            return None, messages
        version = lib.save(codebook_id, cb)
        return version, messages

    def rename_codebook(self, codebook_id: str, new_name: str) -> None:
        self.init_library().rename(codebook_id, new_name)

    def delete_codebook(self, codebook_id: str) -> None:
        self.init_library().delete(codebook_id)

    def duplicate_codebook(self, codebook_id: str, new_name: str) -> CodebookMeta:
        return self.init_library().duplicate(codebook_id, new_name)

    def import_codebook(self, src_path: str, name: str) -> CodebookMeta:
        return self.init_library().import_file(src_path, name)

    def export_codebook(self, codebook_id: str, dest_path: str) -> None:
        self.init_library().export_file(codebook_id, dest_path)

    def list_versions(self, codebook_id: str) -> list[VersionInfo]:
        return self.init_library().list_versions(codebook_id)

    def restore_version(self, codebook_id: str, version_id: str) -> VersionInfo:
        return self.init_library().restore_version(codebook_id, version_id)

    # ======================== 密码本（文件加载） ========================

    def load_codebook(self, path: str) -> CodebookState:
        """加载并校验密码本（同步，通常很快）"""
        cb_state = CodebookState(path=path)
        if not os.path.exists(path):
            cb_state.error = f"密码本文件未找到：{path}"
            return cb_state

        try:
            cb = Codebook(path)
            cb.load()
        except CodebookError as e:
            cb_state.error = str(e)
            return cb_state
        except Exception as e:
            cb_state.error = f"读取密码本失败：{e}"
            return cb_state

        messages = cb.validate()
        error_count = sum(1 for m in messages if m.startswith("ERROR"))
        warning_count = sum(1 for m in messages if m.startswith("WARNING"))

        cb_state.codebook = cb
        cb_state.messages = messages
        cb_state.error_count = error_count
        cb_state.warning_count = warning_count
        cb_state.valid = error_count == 0

        return cb_state

    # ======================== 文件队列 ========================

    def _is_format_allowed(self, fmt: str) -> bool:
        """A-15: 检查文件格式是否在当前格式过滤器中。"""
        return fmt in self.state.format_filters

    def add_files(self, paths: list[str]) -> list[FileItem]:
        """添加文件到队列，返回新增的 FileItem 列表

        使用规范化绝对路径去重，覆盖两种场景：
        - 已在队列中的路径（跨多次调用）
        - 同一次调用中重复出现的路径

        A-15: 手动选择/拖放的文件也检查 format_filters，与目录扫描统一。
        """
        added = []
        seen = {os.path.realpath(f.path) for f in self.state.files}
        for p in paths:
            normalized = os.path.realpath(p)
            if normalized in seen:
                continue
            item = create_file_item(p)
            if item.fmt != "other" and self._is_format_allowed(item.fmt):
                self.state.files.append(item)
                added.append(item)
                seen.add(normalized)
        return added

    def add_folder(self, dir_path: str) -> tuple[list[FileItem], int]:
        """添加目录，返回 (新增文件列表, 跳过的不支持格式文件数)"""
        formats = sorted(self.state.format_filters)
        all_files, skipped, errors = scan_files(dir_path, formats, recursive=True)
        for error in errors:
            logger.warning("目录扫描项失败: %s", error)
        added = self.add_files(all_files)
        return added, skipped

    def add_folder_async(
        self,
        dir_path: str,
        on_complete: Callable[[list[FileItem], int, list[str]], None],
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> bool:
        """后台单次扫描目录；进度和结果通过主线程事件队列交付。"""
        if self._scan_thread and self._scan_thread.is_alive():
            return False
        self._scan_cancel.clear()
        formats = sorted(self.state.format_filters)

        def worker() -> None:
            files, skipped, errors = scan_files(
                dir_path,
                formats,
                recursive=True,
                progress_callback=(
                    (lambda count, path: self._safe_after(on_progress, count, path))
                    if on_progress else None
                ),
                cancel_check=self._scan_cancel.is_set,
            )
            self._safe_after(self._finish_folder_scan, files, skipped, errors, on_complete)

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()
        self._ensure_event_polling()
        return True

    def _finish_folder_scan(self, files, skipped, errors, callback) -> None:
        added = self.add_files(files)
        callback(added, skipped, errors)

    def cancel_folder_scan(self) -> None:
        self._scan_cancel.set()

    def remove_file(self, index: int) -> None:
        """从队列移除文件"""
        if 0 <= index < len(self.state.files):
            self.state.files.pop(index)

    def clear_files(self) -> None:
        """清空文件队列"""
        self.state.files.clear()

    # ======================== 任务执行 ========================

    def execute(
        self,
        on_file_start: FileCallback,
        on_file_done: FileCallback,
        on_progress: ProgressCallback,
        on_complete: TaskCompleteCallback,
    ) -> bool:
        """启动后台任务，返回任务是否成功启动。

        回调均由主线程定时消费事件队列后执行。
        """
        if self.state.task_running or not self.state.can_execute:
            return False

        self._cancel_token = CancelToken()
        self.state.task_running = True
        self.state.reset_file_status()

        self._thread = threading.Thread(
            target=self._run_task,
            args=(on_file_start, on_file_done, on_progress, on_complete),
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception:
            self.state.task_running = False
            raise
        self._ensure_event_polling()
        return True

    def cancel(self) -> None:
        """请求取消任务"""
        if self._cancel_token:
            self._cancel_token.cancel()

    def _run_task(
        self,
        on_file_start: FileCallback,
        on_file_done: FileCallback,
        on_progress: ProgressCallback,
        on_complete: TaskCompleteCallback,
    ) -> None:
        """后台线程：逐文件执行脱敏/恢复"""
        state = self.state
        total = len(state.files)
        results = list(state.files)  # 快照

        # A-12: 创建不可变任务上下文快照，任务期间不依赖可变全局状态
        cb_state = state.codebook
        ctx = TaskContext(
            mode=state.mode,
            codebook=cb_state.codebook,
            codebook_name=cb_state.library_name or (
                os.path.basename(cb_state.path) if cb_state.path else ""
            ),
            codebook_version=cb_state.version or "",
            exact_count=cb_state.exact_count,
            regex_count=cb_state.regex_count,
            output_same_dir=state.output_same_dir,
            output_dir=state.output_dir,
            generate_report=state.generate_report,
            history_enabled=state.history_enabled,
        )
        self._task_context = ctx

        try:
            mode = ctx.mode
            cancel_token = self._cancel_token
            if mode == Mode.MASK:
                engine = Masker(ctx.codebook)
            else:
                engine = Restorer(ctx.codebook)

            for i, item in enumerate(results):
                if cancel_token and cancel_token.is_cancelled:
                    for j in range(i, total):
                        results[j].status = FileStatus.STOPPED
                        self._safe_after(on_file_done, j, results[j])
                    break

                item.status = FileStatus.PROCESSING
                self._safe_after(on_file_start, i, item)
                aggregate_total = total * 100
                self._safe_after(on_progress, i * 100, aggregate_total, f"正在处理 {item.filename}")

                try:
                    handler, fmt = get_handler(item.path)
                    if handler is None:
                        item.status = FileStatus.FAILED
                        item.error_message = f"不支持的文件格式：{fmt}"
                        self._safe_after(on_file_done, i, item)
                        continue

                    suffix = DESENSITIZED_SUFFIX if mode == Mode.MASK else RESTORED_SUFFIX
                    output_dir = None if ctx.output_same_dir else ctx.output_dir
                    output_path = generate_output_path(
                        item.path,
                        output_dir=output_dir,
                        suffix=suffix,
                        output_extension=".docx" if fmt == "doc" else None,
                    )

                    def _handler_progress(current: int, handler_total: int, message: str):
                        progress = i * 100
                        if handler_total > 0:
                            progress += int(current / handler_total * 100)
                        self._safe_after(
                            on_progress, progress, aggregate_total,
                            f"{item.filename}：{message}",
                        )

                    if mode == Mode.MASK:
                        output_path, count, coverage = handler.mask(
                            item.path, engine, output_path=output_path,
                            progress_callback=_handler_progress,
                            cancel_token=cancel_token,
                        )
                        item.output_path = output_path
                        item.replacements = count
                        item.coverage = (
                            engine.generate_coverage_summary(coverage)
                            if ctx.generate_report else None
                        )
                        item.warnings = list(getattr(handler, "last_warnings", []))
                    else:
                        output_path, count = handler.restore(
                            item.path, engine, output_path=output_path,
                            progress_callback=_handler_progress,
                            cancel_token=cancel_token,
                        )
                        item.output_path = output_path
                        item.replacements = count

                    item.status = FileStatus.DONE
                except TaskCancelledError:
                    item.status = FileStatus.STOPPED
                except MaskConflictError as e:
                    item.status = FileStatus.CONFLICT
                    item.conflict_details = str(e)
                except Exception as e:
                    logger.error(f"处理失败: {item.path} - {e}", exc_info=True)
                    item.status = FileStatus.FAILED
                    item.error_message = str(e)
                self._safe_after(on_file_done, i, item)
        except Exception as exc:
            logger.error("后台任务发生未捕获异常: %s", exc, exc_info=True)
            for index, item in enumerate(results):
                if item.status in (FileStatus.WAITING, FileStatus.PROCESSING):
                    item.status = FileStatus.FAILED
                    item.error_message = f"任务初始化失败：{exc}"
                    self._safe_after(on_file_done, index, item)
        finally:
            state.task_running = False
            aggregate_total = total * 100
            self._safe_after(on_progress, aggregate_total, aggregate_total, "任务完成")
            self._safe_after(on_complete, results)
            # 延迟记录历史：让 Tk 先完成 on_complete 触发的页面切换与重绘，
            # 再执行 record_history 的同步磁盘 I/O，避免白屏。
            self._safe_after(self._schedule_record_history, results)

    def _safe_after(self, callback, *args) -> None:
        """工作线程安全投递事件；本方法绝不调用 Tk。"""
        if not self._closed:
            self._event_queue.put((callback, args))

    def process_pending_events(self) -> int:
        """在主线程执行当前队列中的回调，返回执行数量。

        A-06: 每个回调独立 try/except Exception，单个回调异常不阻断后续事件排空。
        BaseException（KeyboardInterrupt/SystemExit）不被吞掉。
        """
        processed = 0
        while True:
            try:
                callback, args = self._event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception:
                logger.exception(
                    "UI 回调异常已隔离，继续排空事件队列: %s",
                    getattr(callback, "__name__", repr(callback)),
                )
            processed += 1
        return processed

    def _ensure_event_polling(self) -> None:
        """只能由主线程调用：启动一次 Tk 定时轮询。"""
        if self._closed or self._event_polling or not self.tk_root:
            return
        self._event_polling = True
        try:
            self.tk_root.after(25, self._poll_events)
        except Exception:
            self._event_polling = False

    def _poll_events(self) -> None:
        """Tk 主线程轮询入口。"""
        self._event_polling = False
        if self._closed:
            return
        self.process_pending_events()
        scan_alive = bool(self._scan_thread and self._scan_thread.is_alive())
        if self.state.task_running or scan_alive or not self._event_queue.empty():
            self._ensure_event_polling()

    def shutdown(self, timeout: float = 2.0) -> None:
        """停止轮询并在有界时间内等待后台线程退出。"""
        self._closed = True
        self.cancel()
        self.cancel_folder_scan()
        deadline = time.monotonic() + max(timeout, 0.0)
        for thread in (self._thread, self._scan_thread):
            if thread and thread.is_alive():
                thread.join(max(0.0, deadline - time.monotonic()))

    # ======================== 工作历史 ========================

    def _schedule_record_history(self, results: list[FileItem]) -> None:
        """通过 Tk after() 延迟执行 record_history，让事件循环先处理重绘。"""
        if self._closed:
            return
        if self.tk_root:
            self.tk_root.after(50, lambda: self.record_history(results))
        else:
            self.record_history(results)

    def record_history(self, results: list[FileItem]) -> None:
        """任务完成后记录历史（主线程执行）。

        A-09: 收集所有 entries 后通过后台线程调用 append_many()，
        避免 Tk 主线程逐条写入磁盘导致 UI 冻结。
        A-12: 使用任务开始时的 TaskContext 快照，不受任务期间 UI 修改影响。
        """
        ctx = self._task_context
        if ctx is None or not ctx.history_enabled:
            return
        if self._history is None:
            self._history = HistoryStore()
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        mode = "mask" if ctx.mode == Mode.MASK else "restore"
        cb_name = ctx.codebook_name
        cb_version = ctx.codebook_version
        exact_count = ctx.exact_count
        regex_count = ctx.regex_count
        entries: list[HistoryEntry] = []
        for item in results:
            status_map = {
                FileStatus.DONE: "done",
                FileStatus.CONFLICT: "conflict",
                FileStatus.FAILED: "failed",
                FileStatus.STOPPED: "stopped",
            }
            status = status_map.get(item.status, "failed")
            entry = HistoryEntry(
                timestamp=timestamp,
                mode=mode,
                input_path=item.path,
                input_filename=item.filename,
                output_path=item.output_path or "",
                codebook_name=cb_name,
                codebook_version=cb_version,
                exact_rule_count=exact_count,
                regex_rule_count=regex_count,
                replacements=item.replacements,
                status=status,
                # A-18: 冲突详情也写入 error 字段，确保历史页面能展示
                error=item.error_message or item.conflict_details,
            )
            entries.append(entry)

        # A-09: 后台线程批量写入，不阻塞 Tk 主线程
        def _write():
            try:
                self._history.append_many(entries)
            except Exception:
                logger.warning("写入历史记录失败", exc_info=True)

        t = threading.Thread(target=_write, daemon=True)
        t.start()

    def query_history(self, limit: int = 100) -> list[HistoryEntry]:
        """查询历史记录。"""
        if self._history is None:
            self._history = HistoryStore()
        return self._history.query(limit=limit)

    def clear_history(self) -> None:
        """清空历史记录。"""
        if self._history is None:
            self._history = HistoryStore()
        self._history.clear()
