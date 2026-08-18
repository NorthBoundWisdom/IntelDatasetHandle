from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.categories import is_good_category
from ..domain.models import Issue, SampleProbe
from .schema import SCHEMA_SQL


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect_database(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=60.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()


def set_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    serialized = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    )
    connection.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, serialized),
    )


def insert_issue(connection: sqlite3.Connection, issue: Issue) -> None:
    connection.execute(
        """
        INSERT INTO issues(sample_id, severity, code, relpath, message, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            issue.sample_id,
            issue.severity.value,
            issue.code,
            issue.relpath,
            issue.message,
            json.dumps(issue.details, ensure_ascii=False, default=str),
        ),
    )


def insert_probe(connection: sqlite3.Connection, probe: SampleProbe) -> None:
    candidate = probe.candidate
    metadata = candidate.metadata
    manifest_relpath = metadata.source_manifest

    connection.execute(
        """
        INSERT INTO samples(
            sample_id, session_id, relpath,
            category_raw, category, is_good, split, weld_type,
            thickness_mm, steel_type, current_a, voltage_v, gas_bar, robot_speed_cpm,
            manifest_relpath, manifest_row, manifest_raw_json, discovered_by_json,
            health_status, total_bytes, image_count,
            primary_video_relpath, primary_audio_relpath, primary_sensor_relpath,
            scanned_at
        ) VALUES (
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?
        )
        """,
        (
            candidate.sample_id,
            candidate.session_id,
            candidate.relpath,
            metadata.category_raw,
            metadata.category,
            None if metadata.category is None else int(is_good_category(metadata.category)),
            metadata.split,
            metadata.weld_type,
            metadata.thickness_mm,
            metadata.steel_type,
            metadata.current_a,
            metadata.voltage_v,
            metadata.gas_bar,
            metadata.robot_speed_cpm,
            manifest_relpath,
            metadata.source_row,
            json.dumps(metadata.raw, ensure_ascii=False, default=str),
            json.dumps(candidate.discovered_by, ensure_ascii=False),
            probe.health_status.value,
            probe.total_bytes,
            probe.image_count,
            probe.primary_video_relpath,
            probe.primary_audio_relpath,
            probe.primary_sensor_relpath,
            utc_now_iso(),
        ),
    )

    connection.executemany(
        """
        INSERT INTO assets(
            asset_id, sample_id, kind, relpath, ordinal,
            size_bytes, mtime_ns, status, metadata_json, sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                asset.asset_id,
                asset.sample_id,
                asset.kind.value,
                asset.relpath,
                asset.ordinal,
                asset.size_bytes,
                asset.mtime_ns,
                asset.status.value,
                json.dumps(asset.metadata, ensure_ascii=False, default=str),
                asset.sha256,
            )
            for asset in probe.assets
        ],
    )

    for issue in probe.issues:
        insert_issue(connection, issue)


def insert_issues(connection: sqlite3.Connection, issues: Iterable[Issue]) -> None:
    for issue in issues:
        insert_issue(connection, issue)
