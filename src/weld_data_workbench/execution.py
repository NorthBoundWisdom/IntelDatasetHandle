from __future__ import annotations

import multiprocessing as mp
import threading
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypeVar

T = TypeVar("T")
ExecutorMode = Literal["thread", "process"]


class ExecutorQueueFullError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    name: str
    slots: int = 1
    mode: ExecutorMode = "thread"
    max_queue: int = 2

    def validate(self) -> None:
        if not self.name:
            raise ValueError("device name cannot be empty")
        if self.slots < 1:
            raise ValueError("device slots must be at least 1")
        if self.max_queue < 0:
            raise ValueError("device max_queue cannot be negative")


class BoundedExecutor:
    """Executor wrapper that bounds both running and queued work."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_queue: int,
        mode: ExecutorMode,
        thread_name_prefix: str = "weld-bounded",
    ):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_queue < 0:
            raise ValueError("max_queue cannot be negative")
        self.max_workers = max_workers
        self.max_queue = max_queue
        self.mode = mode
        self._capacity = threading.BoundedSemaphore(max_workers + max_queue)
        self._lock = threading.Lock()
        self._submitted = 0
        self._completed = 0
        self._rejected = 0
        self._closed = False
        if mode == "thread":
            self._executor: ThreadPoolExecutor | ProcessPoolExecutor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=thread_name_prefix,
            )
        elif mode == "process":
            self._executor = ProcessPoolExecutor(
                max_workers=max_workers,
                mp_context=mp.get_context("spawn"),
            )
        else:  # pragma: no cover
            raise ValueError(f"Unsupported executor mode: {mode}")

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        with self._lock:
            if self._closed:
                raise RuntimeError("executor is closed")
        if not self._capacity.acquire(blocking=False):
            with self._lock:
                self._rejected += 1
            raise ExecutorQueueFullError(
                f"{self.mode} executor queue is full "
                f"({self.max_workers} workers + {self.max_queue} queued)"
            )
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except BaseException:
            self._capacity.release()
            raise
        with self._lock:
            self._submitted += 1

        def release(_future: Future[T]) -> None:
            with self._lock:
                self._completed += 1
            self._capacity.release()

        future.add_done_callback(release)
        return future

    def snapshot(self) -> dict[str, int | str | bool]:
        with self._lock:
            inflight = self._submitted - self._completed
            return {
                "mode": self.mode,
                "max_workers": self.max_workers,
                "max_queue": self.max_queue,
                "submitted": self._submitted,
                "completed": self._completed,
                "inflight": inflight,
                "rejected": self._rejected,
                "closed": self._closed,
            }

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> BoundedExecutor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()


class LearnedJobScheduler:
    """Bounded process/device queues for heavyweight extractors and models."""

    def __init__(
        self,
        *,
        cpu_workers: int = 2,
        cpu_queue: int = 4,
        devices: tuple[DeviceSpec, ...] = (),
    ):
        self.cpu = BoundedExecutor(
            max_workers=cpu_workers,
            max_queue=cpu_queue,
            mode="process",
            thread_name_prefix="weld-learned-cpu",
        )
        self.devices: dict[str, BoundedExecutor] = {}
        self.specs: dict[str, DeviceSpec] = {}
        try:
            for spec in devices:
                spec.validate()
                if spec.name in self.devices:
                    raise ValueError(f"Duplicate device queue: {spec.name}")
                self.specs[spec.name] = spec
                self.devices[spec.name] = BoundedExecutor(
                    max_workers=spec.slots,
                    max_queue=spec.max_queue,
                    mode=spec.mode,
                    thread_name_prefix=f"weld-device-{spec.name.replace(':', '-')}",
                )
        except BaseException:
            self.cpu.shutdown(wait=False, cancel_futures=True)
            for executor in self.devices.values():
                executor.shutdown(wait=False, cancel_futures=True)
            raise

    def submit_cpu(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        return self.cpu.submit(fn, *args, **kwargs)

    def submit_device(
        self,
        device: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[T]:
        executor = self.devices.get(device)
        if executor is None:
            raise KeyError(f"Unknown learned-job device queue: {device}")
        if "device" in kwargs:
            raise ValueError("device is injected by the scheduler and must not be supplied twice")
        kwargs["device"] = device
        return executor.submit(fn, *args, **kwargs)

    def snapshot(self) -> dict[str, Any]:
        return {
            "cpu": self.cpu.snapshot(),
            "devices": {
                name: {"spec": asdict(self.specs[name]), "executor": executor.snapshot()}
                for name, executor in sorted(self.devices.items())
            },
        }

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        self.cpu.shutdown(wait=wait, cancel_futures=cancel_futures)
        for executor in self.devices.values():
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> LearnedJobScheduler:
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
