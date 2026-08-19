from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..sqlite_utils import closing_connection

FEATURE_JOB_SCHEMA_VERSION = 1

# Bump only the affected modality when its feature semantics change. The cache key
# intentionally keeps modality versions independent so an audio change does not
# invalidate video, sensor, or image work.
EXTRACTOR_VERSIONS: dict[str, str] = {
    "audio": "handcrafted-audio-v1",
    "video": "handcrafted-video-v1",
    "sensor": "handcrafted-sensor-v1",
    "image": "handcrafted-image-v1",
}

VALID_JOB_STATES = {"pending", "running", "success", "failed", "stale"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def extractor_config_hash(config: dict[str, Any] | None = None) -> str:
    """Hash only extractor behavior, never output paths or runtime worker counts."""

    return _sha256_json(config or {})


def sample_modality_fingerprint(sample: dict[str, Any], modality: str) -> str:
    """Return a deterministic fingerprint for one sample/modality.

    Current filesystem size/mtime are preferred over index values. This lets the
    derivative cache notice a raw asset that changed after the last index build.
    An indexed content hash is reused only while its indexed stat still matches
    the live file; otherwise it is deliberately ignored as stale metadata.
    """

    kind = "image" if modality in {"image", "images"} else modality
    assets: list[dict[str, Any]] = [
        dict(asset) for asset in sample.get("assets", []) if asset.get("kind") == kind
    ]
    normalized: list[dict[str, Any]] = []
    for asset in sorted(
        assets,
        key=lambda item: (
            int(item.get("ordinal") or 0),
            str(item.get("relpath") or ""),
        ),
    ):
        indexed_size = int(asset.get("size_bytes") or 0)
        indexed_mtime = int(asset.get("mtime_ns") or 0)
        live_size = indexed_size
        live_mtime = indexed_mtime
        exists = True
        absolute = asset.get("absolute_path")
        if absolute:
            path = Path(str(absolute))
            try:
                stat = path.stat()
                live_size = int(stat.st_size)
                live_mtime = int(stat.st_mtime_ns)
            except OSError:
                exists = False

        indexed_sha = asset.get("sha256")
        trustworthy_sha = (
            str(indexed_sha)
            if indexed_sha and exists and live_size == indexed_size and live_mtime == indexed_mtime
            else None
        )
        normalized.append(
            {
                "relpath": str(asset.get("relpath") or ""),
                "ordinal": int(asset.get("ordinal") or 0),
                "size_bytes": live_size,
                "mtime_ns": live_mtime,
                "exists": exists,
                "sha256": trustworthy_sha,
            }
        )

    return _sha256_json(
        {
            "sample_id": str(sample.get("sample_id") or ""),
            "modality": kind,
            "assets": normalized,
        }
    )


def make_cache_key(
    *,
    sample_fingerprint: str,
    modality: str,
    extractor_name: str,
    extractor_version: str,
    config_hash: str,
) -> str:
    return _sha256_json(
        {
            "sample_fingerprint": sample_fingerprint,
            "modality": modality,
            "extractor_name": extractor_name,
            "extractor_version": extractor_version,
            "config_hash": config_hash,
        }
    )


@dataclass(frozen=True, slots=True)
class FeatureJobPlan:
    sample_id: str
    modality: str
    cache_key: str
    sample_fingerprint: str
    extractor_name: str
    extractor_version: str
    config_hash: str
    reused: bool


@dataclass(frozen=True, slots=True)
class FeatureJobResult:
    sample_id: str
    modality: str
    cache_key: str
    status: str
    features: dict[str, Any] | None
    error: str | None
    attempts: int


class FeatureJobStore:
    """Small workspace-local state database for resumable derivative jobs.

    This database is intentionally separate from `index.sqlite3`. The immutable
    dataset index remains a data contract; transient/rebuildable derivative job
    state can evolve independently without forcing an index schema migration.
    """

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with closing_connection(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    sample_id TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    sample_fingerprint TEXT NOT NULL,
                    extractor_name TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    feature_json TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (sample_id, modality)
                );

                CREATE INDEX IF NOT EXISTS idx_feature_jobs_status
                    ON jobs(status, modality, sample_id);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(FEATURE_JOB_SCHEMA_VERSION),),
            )

    def recover_interrupted(self) -> int:
        """Convert jobs left running by a killed process back to pending."""

        with closing_connection(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status='pending',
                    error=CASE
                        WHEN error IS NULL OR error='' THEN 'interrupted_before_completion'
                        ELSE error
                    END,
                    started_at=NULL,
                    updated_at=?
                WHERE status='running'
                """,
                (_utc_now(),),
            )
            return int(cursor.rowcount)

    def plan(
        self,
        *,
        sample_id: str,
        modality: str,
        sample_fingerprint: str,
        extractor_name: str,
        extractor_version: str,
        config: dict[str, Any] | None = None,
        force: bool = False,
    ) -> FeatureJobPlan:
        config_hash = extractor_config_hash(config)
        cache_key = make_cache_key(
            sample_fingerprint=sample_fingerprint,
            modality=modality,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            config_hash=config_hash,
        )
        now = _utc_now()
        with closing_connection(self._connect()) as connection:
            existing = connection.execute(
                "SELECT cache_key, status FROM jobs WHERE sample_id=? AND modality=?",
                (sample_id, modality),
            ).fetchone()
            reused = bool(
                existing
                and not force
                and str(existing["cache_key"]) == cache_key
                and str(existing["status"]) == "success"
            )
            if reused:
                return FeatureJobPlan(
                    sample_id=sample_id,
                    modality=modality,
                    cache_key=cache_key,
                    sample_fingerprint=sample_fingerprint,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                    config_hash=config_hash,
                    reused=True,
                )

            if existing and str(existing["cache_key"]) != cache_key:
                connection.execute(
                    "UPDATE jobs SET status='stale', updated_at=? WHERE sample_id=? AND modality=?",
                    (now, sample_id, modality),
                )

            connection.execute(
                """
                INSERT INTO jobs(
                    sample_id, modality, cache_key, sample_fingerprint,
                    extractor_name, extractor_version, config_hash,
                    status, attempts, feature_json, error,
                    started_at, finished_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, ?)
                ON CONFLICT(sample_id, modality) DO UPDATE SET
                    cache_key=excluded.cache_key,
                    sample_fingerprint=excluded.sample_fingerprint,
                    extractor_name=excluded.extractor_name,
                    extractor_version=excluded.extractor_version,
                    config_hash=excluded.config_hash,
                    status='pending',
                    feature_json=NULL,
                    error=NULL,
                    started_at=NULL,
                    finished_at=NULL,
                    updated_at=excluded.updated_at
                """,
                (
                    sample_id,
                    modality,
                    cache_key,
                    sample_fingerprint,
                    extractor_name,
                    extractor_version,
                    config_hash,
                    now,
                ),
            )

        return FeatureJobPlan(
            sample_id=sample_id,
            modality=modality,
            cache_key=cache_key,
            sample_fingerprint=sample_fingerprint,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            config_hash=config_hash,
            reused=False,
        )

    def mark_running(self, plan: FeatureJobPlan) -> None:
        with closing_connection(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status='running', attempts=attempts+1, started_at=?,
                    finished_at=NULL, error=NULL, updated_at=?
                WHERE sample_id=? AND modality=? AND cache_key=?
                """,
                (
                    _utc_now(),
                    _utc_now(),
                    plan.sample_id,
                    plan.modality,
                    plan.cache_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Feature job disappeared before start: {plan.sample_id}/{plan.modality}"
                )

    def store_success(self, plan: FeatureJobPlan, features: dict[str, Any]) -> None:
        now = _utc_now()
        payload = _canonical_json(features)
        with closing_connection(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status='success', feature_json=?, error=NULL,
                    finished_at=?, updated_at=?
                WHERE sample_id=? AND modality=? AND cache_key=?
                """,
                (
                    payload,
                    now,
                    now,
                    plan.sample_id,
                    plan.modality,
                    plan.cache_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Feature job cache key changed during extraction: {plan.sample_id}/{plan.modality}"
                )

    def store_failure(self, plan: FeatureJobPlan, error: str) -> None:
        now = _utc_now()
        with closing_connection(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status='failed', feature_json=NULL, error=?,
                    finished_at=?, updated_at=?
                WHERE sample_id=? AND modality=? AND cache_key=?
                """,
                (
                    error,
                    now,
                    now,
                    plan.sample_id,
                    plan.modality,
                    plan.cache_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Feature job cache key changed during extraction: {plan.sample_id}/{plan.modality}"
                )

    def result(self, plan: FeatureJobPlan) -> FeatureJobResult:
        with closing_connection(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT sample_id, modality, cache_key, status, attempts, feature_json, error
                FROM jobs
                WHERE sample_id=? AND modality=? AND cache_key=?
                """,
                (plan.sample_id, plan.modality, plan.cache_key),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown feature job: {plan.sample_id}/{plan.modality}")
        features: dict[str, Any] | None = None
        raw = row["feature_json"]
        if raw:
            try:
                parsed = json.loads(str(raw))
                if isinstance(parsed, dict):
                    features = parsed
            except json.JSONDecodeError:
                features = None
        return FeatureJobResult(
            sample_id=str(row["sample_id"]),
            modality=str(row["modality"]),
            cache_key=str(row["cache_key"]),
            status=str(row["status"]),
            features=features,
            error=str(row["error"]) if row["error"] is not None else None,
            attempts=int(row["attempts"]),
        )

    def status_counts(self) -> dict[str, int]:
        with closing_connection(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status"
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}
