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

from docmask.core.codebook import Codebook, CodebookError
from docmask.core.masker import Masker, MaskConflictError
from docmask.core.restorer import Restorer
from docmask.handlers.base import CancelToken, TaskCancelledError
from docmask.services.file_service import scan_files, get_handler
from docmask.utils.file_utils import generate_output_path
from docmask.config import DESENSITIZED_SUFFIX, RESTORED_SUFFIX

from docmask.ui.state import (
    AppState, CodebookState, FileItem, FileStatus, Mode, create_file_item,
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

    # ======================== 密码本 ========================

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

    def add_files(self, paths: list[str]) -> list[FileItem]:
        """添加文件到队列，返回新增的 FileItem 列表

        使用规范化绝对路径去重，覆盖两种场景：
        - 已在队列中的路径（跨多次调用）
        - 同一次调用中重复出现的路径
        """
        added = []
        seen = {os.path.realpath(f.path) for f in self.state.files}
        for p in paths:
            normalized = os.path.realpath(p)
            if normalized in seen:
                continue
            item = create_file_item(p)
            if item.fmt != "other":
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
        try:
            mode = state.mode
            cancel_token = self._cancel_token
            if mode == Mode.MASK:
                engine = Masker(state.codebook.codebook)
            else:
                engine = Restorer(state.codebook.codebook)

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
                    output_dir = None if state.output_same_dir else state.output_dir
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
                            if state.generate_report else None
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

    def _safe_after(self, callback, *args) -> None:
        """工作线程安全投递事件；本方法绝不调用 Tk。"""
        if not self._closed:
            self._event_queue.put((callback, args))

    def process_pending_events(self) -> int:
        """在主线程执行当前队列中的回调，返回执行数量。"""
        processed = 0
        while True:
            try:
                callback, args = self._event_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
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
