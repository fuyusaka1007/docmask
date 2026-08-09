"""UI Controller 任务执行链路测试"""
import threading
from pathlib import Path

from docmask.core.codebook import Codebook, CodebookRule
from docmask.ui.controller import TaskController
from docmask.ui.state import AppState, FileStatus, Mode, create_file_item


class ImmediateTkRoot:
    """记录 after 回调，并断言 Tk API 只从创建线程调用。"""

    def __init__(self):
        self.owner_thread = threading.get_ident()
        self.callbacks = []

    def after(self, _delay, callback):
        assert threading.get_ident() == self.owner_thread
        self.callbacks.append(callback)

    def flush(self):
        while self.callbacks:
            self.callbacks.pop(0)()


def _make_state(tmp_path: Path, output_same_dir: bool = True) -> AppState:
    codebook_path = tmp_path / "codebook.txt"
    codebook_path.write_text("张三==>李四\n", encoding="utf-8")
    codebook = Codebook(str(codebook_path))
    codebook.load()

    input_path = tmp_path / "input.txt"
    input_path.write_text("张三的文件", encoding="utf-8")

    state = AppState()
    state.codebook.codebook = codebook
    state.codebook.valid = True
    state.files = []
    state.history_enabled = False  # 防止测试写入真实历史记录
    state.output_same_dir = output_same_dir
    state.output_dir = str(tmp_path / "output") if not output_same_dir else None
    if state.output_dir:
        Path(state.output_dir).mkdir()
    return state


def _run(controller: TaskController):
    progress = []
    completed = threading.Event()

    started = controller.execute(
        on_file_start=lambda index, item: None,
        on_file_done=lambda index, item: None,
        on_progress=lambda current, total, message: progress.append(
            (current, total, message)
        ),
        on_complete=lambda results: completed.set(),
    )
    assert started is True
    controller._thread.join(timeout=5)
    assert not controller._thread.is_alive()
    controller.tk_root.flush()
    assert completed.is_set()
    return progress


def test_execute_starts_task_and_reports_handler_progress(tmp_path):
    state = _make_state(tmp_path)
    input_path = tmp_path / "input.txt"
    state.files = [create_file_item(str(input_path))]
    controller = TaskController(state, ImmediateTkRoot())

    progress = _run(controller)

    item = state.files[0]
    assert item.status == FileStatus.DONE
    assert Path(item.output_path).name == "input_desensitized.txt"
    assert Path(item.output_path).read_text(encoding="utf-8") == "李四的文件"
    assert progress[0][0] == 0
    assert progress[0][1] == 100
    assert progress[-1] == (100, 100, "任务完成")
    assert any("正在读取文件" in message for _, _, message in progress)
    assert state.task_running is False


def test_execute_resolves_custom_output_directory(tmp_path):
    state = _make_state(tmp_path, output_same_dir=False)
    input_path = tmp_path / "input.txt"
    state.files = [create_file_item(str(input_path))]
    controller = TaskController(state, ImmediateTkRoot())

    _run(controller)

    output_path = Path(state.files[0].output_path)
    assert output_path == tmp_path / "output" / "input_desensitized.txt"
    assert output_path.exists()


def test_execute_restore_uses_restore_suffix(tmp_path):
    state = _make_state(tmp_path)
    input_path = tmp_path / "input.txt"
    masked_path = tmp_path / "masked.txt"
    masked_path.write_text("李四的文件", encoding="utf-8")
    state.mode = Mode.RESTORE
    state.files = [create_file_item(str(masked_path))]
    controller = TaskController(state, ImmediateTkRoot())

    _run(controller)

    output_path = Path(state.files[0].output_path)
    assert output_path.name == "masked_restored.txt"
    assert output_path.read_text(encoding="utf-8") == "张三的文件"


def test_report_switch_off_retains_no_rule_details(tmp_path):
    state = _make_state(tmp_path)
    state.generate_report = False
    state.files = [create_file_item(str(tmp_path / "input.txt"))]
    controller = TaskController(state, ImmediateTkRoot())

    _run(controller)

    assert state.files[0].coverage is None


def test_report_switch_on_uses_anonymous_rule_ids(tmp_path):
    state = _make_state(tmp_path)
    state.generate_report = True
    state.files = [create_file_item(str(tmp_path / "input.txt"))]
    controller = TaskController(state, ImmediateTkRoot())

    _run(controller)

    coverage = state.files[0].coverage
    assert coverage["rules"][0]["id"].startswith("E")
    assert "张三" not in repr(coverage)
    assert "李四" not in repr(coverage)


def test_top_level_worker_failure_completes_once_and_resets_state(tmp_path, monkeypatch):
    state = _make_state(tmp_path)
    state.files = [create_file_item(str(tmp_path / "input.txt"))]
    root = ImmediateTkRoot()
    controller = TaskController(state, root)
    completed = []

    class BrokenMasker:
        def __init__(self, _codebook):
            raise RuntimeError("engine init failed")

    monkeypatch.setattr("docmask.ui.controller.Masker", BrokenMasker)
    assert controller.execute(
        on_file_start=lambda *_: None,
        on_file_done=lambda *_: None,
        on_progress=lambda *_: None,
        on_complete=lambda results: completed.append(results),
    )
    controller._thread.join(timeout=5)
    root.flush()

    assert state.task_running is False
    assert state.files[0].status == FileStatus.FAILED
    assert len(completed) == 1


def test_save_codebook_with_error_does_not_save(tmp_path):
    """A-02: 含 ERROR 的密码本禁止保存，当前版本不变。"""
    state = _make_state(tmp_path)
    controller = TaskController(state, ImmediateTkRoot())

    # 创建密码本并保存有效规则
    meta = controller.create_codebook("测试密码本")
    valid_rules = [
        CodebookRule(rule_type="exact", original="张三", replacement="李四"),
    ]
    version, messages = controller.save_codebook_to_library(meta.id, valid_rules)
    assert version is not None
    assert not any(m.startswith("ERROR") for m in messages)

    # 尝试保存无效规则（脱敏词重复）
    invalid_rules = [
        CodebookRule(rule_type="exact", original="A", replacement="X"),
        CodebookRule(rule_type="exact", original="B", replacement="X"),
    ]
    version2, messages2 = controller.save_codebook_to_library(meta.id, invalid_rules)
    # A-02: 存在 ERROR 时返回 (None, messages)，不保存
    assert version2 is None
    assert any(m.startswith("ERROR") for m in messages2)

    # 当前版本仍为有效规则
    loaded = controller.init_library().load(meta.id)
    assert loaded.exact_rule_count == 1
    assert "张三" in loaded.forward_map
