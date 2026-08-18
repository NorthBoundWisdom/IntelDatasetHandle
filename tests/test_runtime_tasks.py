from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from weld_data_workbench.runtime_tasks import (
    TaskContext,
    TaskManager,
    TaskQueueFullError,
    TaskStore,
)


def _wait_for_state(manager: TaskManager, task_id: str, states: set[str], timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(task_id)
        if record is not None and record.state in states:
            return record
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {states}")


def test_task_manager_persists_progress_and_result(tmp_path: Path) -> None:
    with TaskManager(tmp_path / "tasks.sqlite3", max_workers=1, max_queue=1) as manager:

        def handler(payload: dict[str, object], context: TaskContext) -> dict[str, object]:
            context.report_progress(1, 2, "half")
            context.report_progress(2, 2, "done")
            return {"value": int(payload["value"]) * 2}

        manager.register("double", handler)
        submitted = manager.submit("double", {"value": 21})
        finished = _wait_for_state(manager, submitted.task_id, {"succeeded"})

        assert finished.result == {"value": 42}
        assert finished.progress_current == 2
        assert finished.progress_total == 2
        assert finished.progress_message == "done"

    reopened = TaskStore(tmp_path / "tasks.sqlite3")
    persisted = reopened.get(submitted.task_id)
    assert persisted is not None
    assert persisted.state == "succeeded"
    assert persisted.result == {"value": 42}


def test_task_manager_applies_queue_backpressure(tmp_path: Path) -> None:
    gate = threading.Event()
    started = threading.Event()
    manager = TaskManager(tmp_path / "tasks.sqlite3", max_workers=1, max_queue=0)

    def blocking(_payload: dict[str, object], _context: TaskContext) -> dict[str, object]:
        started.set()
        assert gate.wait(timeout=5.0)
        return {"ok": True}

    manager.register("blocking", blocking)
    first = manager.submit("blocking", {})
    assert started.wait(timeout=2.0)
    with pytest.raises(TaskQueueFullError):
        manager.submit("blocking", {})
    gate.set()
    _wait_for_state(manager, first.task_id, {"succeeded"})
    manager.shutdown()


def test_running_task_cooperatively_cancels(tmp_path: Path) -> None:
    manager = TaskManager(tmp_path / "tasks.sqlite3", max_workers=1, max_queue=1)

    def cancellable(_payload: dict[str, object], context: TaskContext) -> dict[str, object]:
        for index in range(200):
            context.report_progress(index, 200, "working")
            time.sleep(0.002)
        return {"unexpected": True}

    manager.register("cancellable", cancellable)
    submitted = manager.submit("cancellable", {})
    _wait_for_state(manager, submitted.task_id, {"running"})
    cancelled = manager.cancel(submitted.task_id)
    assert cancelled is not None
    finished = _wait_for_state(manager, submitted.task_id, {"cancelled"})
    assert finished.cancel_requested is True
    manager.shutdown()


def test_store_recovers_interrupted_running_task(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    record = store.create("demo", {})
    assert store.mark_running(record.task_id)
    assert store.recover_interrupted() == 1
    recovered = store.get(record.task_id)
    assert recovered is not None
    assert recovered.state == "failed"
    assert "interrupted" in str(recovered.error)
