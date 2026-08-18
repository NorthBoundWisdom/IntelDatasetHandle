from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

TaskState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TaskHandler = Callable[[dict[str, Any], "TaskContext"], dict[str, Any] | None]


class TaskQueueFullError(RuntimeError):
    pass


class TaskCancelledError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    kind: str
    state: TaskState
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    progress_current: int
    progress_total: int
    progress_message: str | None
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskStore:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_state_updated
                    ON tasks(state, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_kind_updated
                    ON tasks(kind, updated_at DESC);
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> TaskRecord:
        result_raw = row["result_json"]
        return TaskRecord(
            task_id=str(row["task_id"]),
            kind=str(row["kind"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            payload=json.loads(str(row["payload_json"])),
            result=json.loads(str(result_raw)) if result_raw is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            progress_current=int(row["progress_current"]),
            progress_total=int(row["progress_total"]),
            progress_message=(
                str(row["progress_message"]) if row["progress_message"] is not None else None
            ),
            cancel_requested=bool(row["cancel_requested"]),
            created_at=str(row["created_at"]),
            started_at=str(row["started_at"]) if row["started_at"] is not None else None,
            finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
            updated_at=str(row["updated_at"]),
        )

    def create(self, kind: str, payload: dict[str, Any]) -> TaskRecord:
        now = _utcnow()
        task_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, kind, state, payload_json, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (task_id, kind, json.dumps(payload, sort_keys=True), now, now),
            )
        record = self.get(task_id)
        if record is None:  # pragma: no cover
            raise RuntimeError("created task disappeared")
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._decode(row) if row is not None else None

    def list(
        self,
        *,
        state: TaskState | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if state is not None:
            clauses.append("state = ?")
            parameters.append(state)
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(limit, 5000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks{where} ORDER BY created_at DESC LIMIT ?", parameters
            ).fetchall()
        return [self._decode(row) for row in rows]

    def mark_running(self, task_id: str) -> bool:
        now = _utcnow()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET state = 'running', started_at = ?, updated_at = ?
                WHERE task_id = ? AND state = 'queued' AND cancel_requested = 0
                """,
                (now, now, task_id),
            )
        return cursor.rowcount == 1

    def report_progress(
        self,
        task_id: str,
        current: int,
        total: int,
        message: str | None = None,
    ) -> None:
        current = max(0, int(current))
        total = max(0, int(total))
        if total and current > total:
            current = total
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET progress_current = ?, progress_total = ?, progress_message = ?, updated_at = ?
                WHERE task_id = ? AND state IN ('queued', 'running')
                """,
                (current, total, message, _utcnow(), task_id),
            )

    def request_cancel(self, task_id: str) -> TaskRecord | None:
        now = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks SET cancel_requested = 1, updated_at = ?
                WHERE task_id = ? AND state IN ('queued', 'running')
                """,
                (now, task_id),
            )
            connection.execute(
                """
                UPDATE tasks
                SET state = 'cancelled', finished_at = ?, updated_at = ?
                WHERE task_id = ? AND state = 'queued'
                """,
                (now, now, task_id),
            )
        return self.get(task_id)

    def cancellation_requested(self, task_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return bool(row[0]) if row is not None else True

    def finish_success(self, task_id: str, result: dict[str, Any] | None) -> None:
        now = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET state = 'succeeded', result_json = ?, error = NULL,
                    finished_at = ?, updated_at = ?
                WHERE task_id = ? AND state = 'running'
                """,
                (json.dumps(result or {}, sort_keys=True), now, now, task_id),
            )

    def finish_failure(self, task_id: str, error: str) -> None:
        now = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET state = 'failed', error = ?, finished_at = ?, updated_at = ?
                WHERE task_id = ? AND state = 'running'
                """,
                (error, now, now, task_id),
            )

    def finish_cancelled(self, task_id: str) -> None:
        now = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET state = 'cancelled', finished_at = ?, updated_at = ?
                WHERE task_id = ? AND state IN ('queued', 'running')
                """,
                (now, now, task_id),
            )

    def recover_interrupted(self) -> int:
        now = _utcnow()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET state = 'failed',
                    error = COALESCE(error, 'worker process interrupted before completion'),
                    finished_at = ?, updated_at = ?
                WHERE state = 'running'
                """,
                (now, now),
            )
        return int(cursor.rowcount)


@dataclass(slots=True)
class TaskContext:
    task_id: str
    store: TaskStore

    @property
    def cancel_requested(self) -> bool:
        return self.store.cancellation_requested(self.task_id)

    def check_cancelled(self) -> None:
        if self.cancel_requested:
            raise TaskCancelledError(f"Task {self.task_id} was cancelled")

    def report_progress(self, current: int, total: int, message: str | None = None) -> None:
        self.store.report_progress(self.task_id, current, total, message)
        self.check_cancelled()


class TaskManager:
    def __init__(
        self,
        path: Path,
        *,
        max_workers: int = 4,
        max_queue: int = 64,
    ):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_queue < 0:
            raise ValueError("max_queue cannot be negative")
        self.store = TaskStore(path)
        self.store.recover_interrupted()
        self._handlers: dict[str, TaskHandler] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="weld-task")
        self._capacity = threading.BoundedSemaphore(max_workers + max_queue)
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()
        self._closed = False

    def register(self, kind: str, handler: TaskHandler) -> None:
        if not kind:
            raise ValueError("task kind cannot be empty")
        with self._lock:
            self._handlers[kind] = handler

    def submit(self, kind: str, payload: dict[str, Any]) -> TaskRecord:
        with self._lock:
            if self._closed:
                raise RuntimeError("task manager is closed")
            handler = self._handlers.get(kind)
        if handler is None:
            raise KeyError(f"No task handler registered for {kind}")
        if not self._capacity.acquire(blocking=False):
            raise TaskQueueFullError("background task queue is full")
        record = self.store.create(kind, payload)
        try:
            future = self._executor.submit(self._run_task, record.task_id, handler)
        except BaseException:
            self._capacity.release()
            self.store.finish_cancelled(record.task_id)
            raise
        with self._lock:
            self._futures[record.task_id] = future
            if future.done():
                self._futures.pop(record.task_id, None)
        return record

    def _run_task(self, task_id: str, handler: TaskHandler) -> None:
        try:
            if not self.store.mark_running(task_id):
                return
            record = self.store.get(task_id)
            if record is None:
                return
            context = TaskContext(task_id=task_id, store=self.store)
            context.check_cancelled()
            result = handler(record.payload, context)
            context.check_cancelled()
            self.store.finish_success(task_id, result)
        except TaskCancelledError:
            self.store.finish_cancelled(task_id)
        except BaseException as exc:
            self.store.finish_failure(task_id, f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._futures.pop(task_id, None)
            self._capacity.release()

    def cancel(self, task_id: str) -> TaskRecord | None:
        return self.store.request_cancel(task_id)

    def get(self, task_id: str) -> TaskRecord | None:
        return self.store.get(task_id)

    def list(
        self,
        *,
        state: TaskState | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        return self.store.list(state=state, kind=kind, limit=limit)

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            self._closed = True
        if cancel_futures:
            for record in self.store.list(state="queued", limit=5000):
                self.store.request_cancel(record.task_id)
            for record in self.store.list(state="running", limit=5000):
                self.store.request_cancel(record.task_id)
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> TaskManager:
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
