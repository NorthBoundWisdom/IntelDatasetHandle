from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import AppConfig
from .index.database import connect_database
from .index.repository import DatasetRepository
from .io.paths import safe_join

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotVerificationError(RuntimeError):
    """Raised when a persisted snapshot no longer matches the indexed dataset."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_distribution(connection, *, kind: str, field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    rows = connection.execute(
        "SELECT metadata_json FROM assets WHERE kind = ? ORDER BY asset_id", (kind,)
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row[0]) if row[0] else {}
        except (TypeError, json.JSONDecodeError):
            continue
        raw = metadata.get(field)
        if raw is None:
            continue
        key = str(raw)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _video_resolution_distribution(connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in connection.execute(
        "SELECT metadata_json FROM assets WHERE kind='video' ORDER BY asset_id"
    ).fetchall():
        try:
            metadata = json.loads(row[0]) if row[0] else {}
        except (TypeError, json.JSONDecodeError):
            continue
        width = metadata.get("width")
        height = metadata.get("height")
        if not width or not height:
            continue
        key = f"{int(width)}x{int(height)}"
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _canonical_index_digest(index_path: Path) -> str:
    """Hash stable semantic rows rather than SQLite file bytes.

    SQLite pages and build timestamps can change across equivalent rebuilds, so a raw
    database hash is deliberately not used for snapshot identity.
    """

    digest = hashlib.sha256()
    with connect_database(index_path, read_only=True) as connection:
        sample_columns = (
            "sample_id,session_id,relpath,category_raw,category,is_good,split,"
            "weld_type,thickness_mm,steel_type,current_a,voltage_v,gas_bar,"
            "robot_speed_cpm,manifest_relpath,manifest_row,health_status,total_bytes,image_count"
        )
        for row in connection.execute(f"SELECT {sample_columns} FROM samples ORDER BY sample_id"):
            digest.update(_canonical_json(list(row)).encode("utf-8"))
            digest.update(b"\n")

        for row in connection.execute(
            "SELECT sample_id,kind,ordinal,relpath,size_bytes,mtime_ns,status,sha256 "
            "FROM assets ORDER BY sample_id,kind,ordinal,relpath"
        ):
            digest.update(_canonical_json(list(row)).encode("utf-8"))
            digest.update(b"\n")

        for row in connection.execute(
            "SELECT severity,code,sample_id,relpath,details_json "
            "FROM issues ORDER BY severity,code,COALESCE(sample_id,''),COALESCE(relpath,''),issue_id"
        ):
            digest.update(_canonical_json(list(row)).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def _category_split_distribution(connection) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    rows = connection.execute(
        "SELECT COALESCE(category,'Unknown'), COALESCE(split,'Unknown'), COUNT(*) "
        "FROM samples GROUP BY category, split ORDER BY category, split"
    ).fetchall()
    for category, split, count in rows:
        result.setdefault(str(category), {})[str(split)] = int(count)
    return result


def _sensor_schema_distribution(connection) -> dict[str, int]:
    result: dict[str, int] = {}
    rows = connection.execute(
        "SELECT metadata_json FROM assets WHERE kind='sensor' ORDER BY asset_id"
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row[0]) if row[0] else {}
        except (TypeError, json.JSONDecodeError):
            continue
        columns = metadata.get("columns") or []
        key = " | ".join(map(str, columns))
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _missing_modality_counts(connection) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN primary_video_relpath IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN primary_audio_relpath IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN primary_sensor_relpath IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN image_count = 0 THEN 1 ELSE 0 END)
        FROM samples
        """
    ).fetchone()
    return {
        "video": int(row[0] or 0),
        "audio": int(row[1] or 0),
        "sensor": int(row[2] or 0),
        "image": int(row[3] or 0),
    }


def _live_asset_integrity(config: AppConfig, connection) -> dict[str, Any]:
    """Stat every indexed asset without decoding media or hashing large files."""

    checked = 0
    missing = 0
    stat_mismatch = 0
    path_errors = 0
    io_errors = 0
    examples: dict[str, list[str]] = {
        "missing": [],
        "stat_mismatch": [],
        "path_error": [],
        "io_error": [],
    }
    rows = connection.execute(
        "SELECT relpath, size_bytes, mtime_ns FROM assets ORDER BY relpath"
    ).fetchall()
    for relpath, indexed_size, indexed_mtime in rows:
        checked += 1
        relpath = str(relpath)
        try:
            path = safe_join(config.dataset_root, relpath)
        except ValueError:
            path_errors += 1
            if len(examples["path_error"]) < 10:
                examples["path_error"].append(relpath)
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            missing += 1
            if len(examples["missing"]) < 10:
                examples["missing"].append(relpath)
            continue
        except OSError:
            io_errors += 1
            if len(examples["io_error"]) < 10:
                examples["io_error"].append(relpath)
            continue
        if int(stat.st_size) != int(indexed_size) or int(stat.st_mtime_ns) != int(indexed_mtime):
            stat_mismatch += 1
            if len(examples["stat_mismatch"]) < 10:
                examples["stat_mismatch"].append(relpath)

    return {
        "checked": checked,
        "missing": missing,
        "stat_mismatch": stat_mismatch,
        "path_errors": path_errors,
        "io_errors": io_errors,
        "examples": examples,
    }


def build_snapshot_payload(
    config: AppConfig, *, archive_path: Path | None = None
) -> dict[str, Any]:
    repo = DatasetRepository(config.index_path, config.dataset_root)
    stats = repo.stats()
    meta = repo.meta()

    manifest_sha256: str | None = None
    manifest_path = meta.get("manifest_path")
    if manifest_path:
        try:
            candidate = safe_join(config.dataset_root, str(manifest_path))
        except ValueError:
            candidate = Path(str(manifest_path)).expanduser().resolve()
        if candidate.is_file():
            manifest_sha256 = sha256_file(candidate)

    archive_sha256: str | None = None
    archive_size_bytes: int | None = None
    if archive_path is not None:
        archive = archive_path.expanduser().resolve()
        if archive.is_file():
            archive_sha256 = sha256_file(archive)
            archive_size_bytes = archive.stat().st_size

    with connect_database(config.index_path, read_only=True) as connection:
        payload: dict[str, Any] = {
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "tool_version": __version__,
            "index_schema_version": meta.get("schema_version"),
            "probe_mode": meta.get("probe_mode"),
            "manifest": {
                "relpath": manifest_path,
                "sha256": manifest_sha256,
                "rows": meta.get("manifest_rows"),
                "columns": meta.get("manifest_columns"),
            },
            "archive": {
                "sha256": archive_sha256,
                "size_bytes": archive_size_bytes,
            },
            "counts": {
                "samples": int(stats["total_samples"]),
                "sessions": int(stats["total_sessions"]),
                "assets": int(stats["total_assets"]),
                "bytes": int(stats["total_bytes"]),
                "issues": int(stats["total_issues"]),
            },
            "category_split": _category_split_distribution(connection),
            "assets_by_kind": dict(sorted(stats["assets_by_kind"].items())),
            "missing_modalities": _missing_modality_counts(connection),
            "health": dict(sorted(stats["by_health"].items())),
            "issues_by_severity": dict(sorted(stats["issues_by_severity"].items())),
            "audio_sample_rates_hz": _metadata_distribution(
                connection, kind="audio", field="sample_rate_hz"
            ),
            "audio_channels": _metadata_distribution(connection, kind="audio", field="channels"),
            "video_fps": _metadata_distribution(connection, kind="video", field="fps"),
            "video_codecs": _metadata_distribution(connection, kind="video", field="fourcc"),
            "video_resolutions": _video_resolution_distribution(connection),
            "sensor_schemas": _sensor_schema_distribution(connection),
            "live_asset_integrity": _live_asset_integrity(config, connection),
            "canonical_index_sha256": _canonical_index_digest(config.index_path),
        }
    return payload


def snapshot_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    snapshot_id: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "payload": self.payload,
        }


def create_snapshot(
    config: AppConfig,
    *,
    archive_path: Path | None = None,
    output: Path | None = None,
) -> DatasetSnapshot:
    payload = build_snapshot_payload(config, archive_path=archive_path)
    snapshot = DatasetSnapshot(
        snapshot_id=snapshot_id(payload),
        payload=payload,
        created_at=datetime.now(UTC).isoformat(),
    )
    if output is not None:
        destination = output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return snapshot


def load_snapshot(path: Path) -> DatasetSnapshot:
    raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    return DatasetSnapshot(
        snapshot_id=str(raw["snapshot_id"]),
        payload=dict(raw["payload"]),
        created_at=str(raw.get("created_at", "")),
    )


def verify_snapshot(
    config: AppConfig,
    snapshot: DatasetSnapshot,
    *,
    archive_path: Path | None = None,
) -> None:
    expected_from_file = snapshot_id(snapshot.payload)
    if expected_from_file != snapshot.snapshot_id:
        raise SnapshotVerificationError(
            "Snapshot document is internally inconsistent: payload hash does not match snapshot_id"
        )
    current = build_snapshot_payload(config, archive_path=archive_path)
    current_id = snapshot_id(current)
    if current_id != snapshot.snapshot_id:
        raise SnapshotVerificationError(
            f"Snapshot mismatch: expected {snapshot.snapshot_id}, current {current_id}"
        )
