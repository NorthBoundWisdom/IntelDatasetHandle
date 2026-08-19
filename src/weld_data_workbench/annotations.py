from __future__ import annotations

import builtins
import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VALID_TARGET_TYPES = {"sample", "issue"}
VALID_DISPOSITIONS = {
    "open",
    "accepted",
    "rejected",
    "resolved",
    "needs_review",
    "ignored",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def issue_target_key(
    sample_id: str,
    code: str,
    *,
    relpath: str | None = None,
    message: str | None = None,
) -> str:
    payload = json.dumps(
        [sample_id, code, relpath or "", message or ""],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{sample_id}:{code}:{digest}"


class AnnotationConflictError(RuntimeError):
    """Raised when optimistic revision matching fails."""


@dataclass(frozen=True, slots=True)
class AnnotationRecord:
    target_type: str
    target_key: str
    sample_id: str
    disposition: str
    note: str
    tags: tuple[str, ...]
    revision: int
    created_at: str
    updated_at: str
    updated_by: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


class AnnotationStore:
    """Mutable operator overlay that never modifies the dataset index."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS annotations (
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT,
                    PRIMARY KEY(target_type, target_key)
                );

                CREATE INDEX IF NOT EXISTS idx_annotations_sample
                    ON annotations(sample_id);
                CREATE INDEX IF NOT EXISTS idx_annotations_disposition
                    ON annotations(disposition);

                CREATE TABLE IF NOT EXISTS annotation_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_annotation_history_target
                    ON annotation_history(target_type, target_key, history_id);
                """
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> AnnotationRecord:
        raw_tags = json.loads(row["tags_json"])
        tags = tuple(str(value) for value in raw_tags)
        return AnnotationRecord(
            target_type=str(row["target_type"]),
            target_key=str(row["target_key"]),
            sample_id=str(row["sample_id"]),
            disposition=str(row["disposition"]),
            note=str(row["note"]),
            tags=tags,
            revision=int(row["revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            updated_by=None if row["updated_by"] is None else str(row["updated_by"]),
        )

    @staticmethod
    def _validate(target_type: str, disposition: str) -> None:
        if target_type not in VALID_TARGET_TYPES:
            raise ValueError(f"Unsupported annotation target_type: {target_type}")
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"Unsupported annotation disposition: {disposition}")

    def get(self, target_type: str, target_key: str) -> AnnotationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM annotations
                WHERE target_type = ? AND target_key = ?
                """,
                (target_type, target_key),
            ).fetchone()
        return None if row is None else self._record(row)

    def list(
        self,
        *,
        target_type: str | None = None,
        sample_id: str | None = None,
        disposition: str | None = None,
        limit: int = 1000,
    ) -> list[AnnotationRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_type is not None:
            if target_type not in VALID_TARGET_TYPES:
                raise ValueError(f"Unsupported annotation target_type: {target_type}")
            clauses.append("target_type = ?")
            params.append(target_type)
        if sample_id is not None:
            clauses.append("sample_id = ?")
            params.append(sample_id)
        if disposition is not None:
            if disposition not in VALID_DISPOSITIONS:
                raise ValueError(f"Unsupported annotation disposition: {disposition}")
            clauses.append("disposition = ?")
            params.append(disposition)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(min(max(int(limit), 1), 100_000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM annotations
                """
                + where
                + " ORDER BY updated_at DESC, target_type, target_key LIMIT ?",
                params,
            ).fetchall()
        return [self._record(row) for row in rows]

    def upsert(
        self,
        *,
        target_type: str,
        target_key: str,
        sample_id: str,
        disposition: str,
        note: str = "",
        tags: Sequence[str] = (),
        updated_by: str | None = None,
        expected_revision: int | None = None,
    ) -> AnnotationRecord:
        target_type = str(target_type).strip().casefold()
        target_key = str(target_key).strip()
        sample_id = str(sample_id).strip()
        disposition = str(disposition).strip().casefold()
        if not target_key:
            raise ValueError("target_key cannot be empty")
        if not sample_id:
            raise ValueError("sample_id cannot be empty")
        self._validate(target_type, disposition)
        normalized_tags = sorted({str(value).strip() for value in tags if str(value).strip()})
        now = utc_now_iso()

        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    """
                    SELECT * FROM annotations
                    WHERE target_type = ? AND target_key = ?
                    """,
                    (target_type, target_key),
                ).fetchone()
                if current is None:
                    if expected_revision not in {None, 0}:
                        raise AnnotationConflictError(
                            f"Annotation does not exist; expected revision {expected_revision}"
                        )
                    revision = 1
                    created_at = now
                else:
                    current_revision = int(current["revision"])
                    if expected_revision is not None and expected_revision != current_revision:
                        raise AnnotationConflictError(
                            f"Revision mismatch: expected {expected_revision}, current {current_revision}"
                        )
                    revision = current_revision + 1
                    created_at = str(current["created_at"])

                connection.execute(
                    """
                    INSERT INTO annotations(
                        target_type, target_key, sample_id, disposition, note,
                        tags_json, revision, created_at, updated_at, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(target_type, target_key) DO UPDATE SET
                        sample_id=excluded.sample_id,
                        disposition=excluded.disposition,
                        note=excluded.note,
                        tags_json=excluded.tags_json,
                        revision=excluded.revision,
                        updated_at=excluded.updated_at,
                        updated_by=excluded.updated_by
                    """,
                    (
                        target_type,
                        target_key,
                        sample_id,
                        disposition,
                        note,
                        json.dumps(normalized_tags, ensure_ascii=False),
                        revision,
                        created_at,
                        now,
                        updated_by,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM annotations
                    WHERE target_type = ? AND target_key = ?
                    """,
                    (target_type, target_key),
                ).fetchone()
                assert row is not None
                record = self._record(row)
                connection.execute(
                    """
                    INSERT INTO annotation_history(
                        target_type, target_key, sample_id, revision,
                        action, snapshot_json, recorded_at
                    ) VALUES (?, ?, ?, ?, 'upsert', ?, ?)
                    """,
                    (
                        target_type,
                        target_key,
                        sample_id,
                        revision,
                        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                connection.commit()
                return record
            except Exception:
                connection.rollback()
                raise

    def history(
        self,
        target_type: str,
        target_key: str,
        *,
        limit: int = 1000,
    ) -> builtins.list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT history_id, target_type, target_key, sample_id,
                       revision, action, snapshot_json, recorded_at
                FROM annotation_history
                WHERE target_type = ? AND target_key = ?
                ORDER BY history_id
                LIMIT ?
                """,
                (target_type, target_key, min(max(int(limit), 1), 100_000)),
            ).fetchall()
        return [
            {
                "history_id": int(row["history_id"]),
                "target_type": str(row["target_type"]),
                "target_key": str(row["target_key"]),
                "sample_id": str(row["sample_id"]),
                "revision": int(row["revision"]),
                "action": str(row["action"]),
                "snapshot": json.loads(row["snapshot_json"]),
                "recorded_at": str(row["recorded_at"]),
            }
            for row in rows
        ]
