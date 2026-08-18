from __future__ import annotations

import threading
from concurrent.futures import Future

import pytest

from weld_data_workbench.execution import (
    BoundedExecutor,
    DeviceSpec,
    ExecutorQueueFullError,
    LearnedJobScheduler,
)


def _square(value: int) -> int:
    return value * value


def _device_echo(value: int, *, device: str) -> tuple[int, str]:
    return value, device


def test_bounded_thread_executor_rejects_excess_queue() -> None:
    gate = threading.Event()
    started = threading.Event()

    def block() -> int:
        started.set()
        assert gate.wait(timeout=5.0)
        return 7

    executor = BoundedExecutor(max_workers=1, max_queue=0, mode="thread")
    first = executor.submit(block)
    assert started.wait(timeout=2.0)
    with pytest.raises(ExecutorQueueFullError):
        executor.submit(_square, 3)
    gate.set()
    assert first.result(timeout=5.0) == 7
    snapshot = executor.snapshot()
    assert snapshot["submitted"] == 1
    assert snapshot["completed"] == 1
    assert snapshot["rejected"] == 1
    executor.shutdown()


def test_spawn_process_executor_runs_picklable_job() -> None:
    with BoundedExecutor(max_workers=1, max_queue=1, mode="process") as executor:
        future = executor.submit(_square, 9)
        assert isinstance(future, Future)
        assert future.result(timeout=15.0) == 81


def test_learned_scheduler_injects_explicit_device() -> None:
    with LearnedJobScheduler(
        cpu_workers=1,
        cpu_queue=1,
        devices=(DeviceSpec("mps", slots=1, mode="thread", max_queue=1),),
    ) as scheduler:
        device_future = scheduler.submit_device("mps", _device_echo, 5)
        assert device_future.result(timeout=5.0) == (5, "mps")
        cpu_future = scheduler.submit_cpu(_square, 4)
        assert cpu_future.result(timeout=15.0) == 16
        snapshot = scheduler.snapshot()
        assert "mps" in snapshot["devices"]


def test_learned_scheduler_rejects_unknown_device() -> None:
    with (
        LearnedJobScheduler(cpu_workers=1, cpu_queue=0) as scheduler,
        pytest.raises(KeyError, match="Unknown learned-job device"),
    ):
        scheduler.submit_device("cuda:9", _device_echo, 1)
