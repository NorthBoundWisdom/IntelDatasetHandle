from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, SENSOR_EXTENSIONS, VIDEO_EXTENSIONS
from ..domain.models import (
    AssetKind,
    AssetProbe,
    HealthStatus,
    Issue,
    SampleCandidate,
    SampleProbe,
    Severity,
)
from ..io.paths import relative_posix, safe_join
from .database import connect_database

PROBE_CACHE_VERSION = 1
_PROBE_RANK = {"none": 0, "light": 1, "full": 2}


def scan_contract(config: AppConfig) -> dict[str, Any]:
    """Settings that affect reusable sample probe semantics."""

    return {
        "probe_cache_version": PROBE_CACHE_VERSION,
        "probe_mode": config.scan.probe_mode,
        "compute_sha256": bool(config.scan.compute_sha256),
        "max_sensor_preview_rows": int(config.scan.max_sensor_preview_rows),
        "expected_post_weld_images": int(config.validation.expected_post_weld_images),
    }


def _load_meta(connection: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in connection.execute("SELECT key, value FROM meta").fetchall():
        try:
            result[str(key)] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            result[str(key)] = value
    return result


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _candidate_metadata_payload(candidate: SampleCandidate) -> dict[str, Any]:
    metadata = candidate.metadata
    return {
        "sample_id": candidate.sample_id,
        "session_id": candidate.session_id,
        "relpath": candidate.relpath,
        "category_raw": metadata.category_raw,
        "category": metadata.category,
        "split": metadata.split,
        "weld_type": metadata.weld_type,
        "thickness_mm": metadata.thickness_mm,
        "steel_type": metadata.steel_type,
        "current_a": metadata.current_a,
        "voltage_v": metadata.voltage_v,
        "gas_bar": metadata.gas_bar,
        "robot_speed_cpm": metadata.robot_speed_cpm,
        "manifest_relpath": metadata.source_manifest,
        "manifest_row": metadata.source_row,
        "manifest_raw": metadata.raw,
        "discovered_by": sorted(candidate.discovered_by),
    }


def _row_metadata_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        manifest_raw = json.loads(row["manifest_raw_json"] or "{}")
    except json.JSONDecodeError:
        manifest_raw = {}
    try:
        discovered_by = json.loads(row["discovered_by_json"] or "[]")
    except json.JSONDecodeError:
        discovered_by = []
    return {
        "sample_id": row["sample_id"],
        "session_id": row["session_id"],
        "relpath": row["relpath"],
        "category_raw": row["category_raw"],
        "category": row["category"],
        "split": row["split"],
        "weld_type": row["weld_type"],
        "thickness_mm": row["thickness_mm"],
        "steel_type": row["steel_type"],
        "current_a": row["current_a"],
        "voltage_v": row["voltage_v"],
        "gas_bar": row["gas_bar"],
        "robot_speed_cpm": row["robot_speed_cpm"],
        "manifest_relpath": row["manifest_relpath"],
        "manifest_row": row["manifest_row"],
        "manifest_raw": manifest_raw,
        "discovered_by": sorted(discovered_by),
    }


def _asset_files(candidate: SampleCandidate) -> list[tuple[AssetKind, Path]]:
    path = candidate.sample_path
    if not path.is_dir():
        return []

    assets: list[tuple[AssetKind, Path]] = []
    direct_files = sorted(
        (item for item in path.iterdir() if item.is_file()),
        key=lambda item: item.name.casefold(),
    )
    for item in direct_files:
        suffix = item.suffix.casefold()
        if suffix in VIDEO_EXTENSIONS:
            assets.append((AssetKind.VIDEO, item))
        elif suffix in AUDIO_EXTENSIONS:
            assets.append((AssetKind.AUDIO, item))
        elif suffix in SENSOR_EXTENSIONS:
            assets.append((AssetKind.SENSOR, item))
        elif suffix in IMAGE_EXTENSIONS:
            assets.append((AssetKind.IMAGE, item))

    images_dir = path / "images"
    if images_dir.is_dir():
        for item in sorted(images_dir.rglob("*"), key=lambda value: value.as_posix().casefold()):
            if item.is_file() and item.suffix.casefold() in IMAGE_EXTENSIONS:
                assets.append((AssetKind.IMAGE, item))
    return assets


def _live_asset_signature(
    candidate: SampleCandidate,
    dataset_root: Path,
) -> list[tuple[str, int, str, int, int]] | None:
    counts = {kind: 0 for kind in AssetKind}
    result: list[tuple[str, int, str, int, int]] = []
    try:
        for kind, path in _asset_files(candidate):
            ordinal = counts[kind]
            counts[kind] += 1
            stat = path.stat()
            result.append(
                (
                    kind.value,
                    ordinal,
                    relative_posix(path, dataset_root),
                    int(stat.st_size),
                    int(stat.st_mtime_ns),
                )
            )
    except (OSError, ValueError):
        return None
    return sorted(result)


class PreviousIndexReuse:
    """Read unchanged sample probe results from the previous atomic index."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.connection: sqlite3.Connection | None = None
        self.compatible = False
        self.previous_sample_ids: set[str] = set()
        if not config.index_path.exists():
            return
        try:
            connection = connect_database(config.index_path, read_only=True)
            meta = _load_meta(connection)
        except (OSError, sqlite3.DatabaseError):
            return

        self.connection = connection
        self.previous_sample_ids = {
            str(row[0]) for row in connection.execute("SELECT sample_id FROM samples").fetchall()
        }
        self.compatible = self._is_compatible(meta)

    def _is_compatible(self, meta: dict[str, Any]) -> bool:
        if int(meta.get("schema_version", -1)) != int(self.config.schema_version):
            return False
        old_contract = meta.get("scan_contract")
        if not isinstance(old_contract, dict):
            return False
        if int(old_contract.get("probe_cache_version", -1)) != PROBE_CACHE_VERSION:
            return False

        old_mode = str(old_contract.get("probe_mode", ""))
        new_mode = self.config.scan.probe_mode
        if old_mode not in _PROBE_RANK or new_mode not in _PROBE_RANK:
            return False
        if _PROBE_RANK[old_mode] < _PROBE_RANK[new_mode]:
            return False
        if self.config.scan.compute_sha256 and not bool(old_contract.get("compute_sha256")):
            return False
        if int(old_contract.get("max_sensor_preview_rows", -1)) != int(
            self.config.scan.max_sensor_preview_rows
        ):
            return False
        return int(old_contract.get("expected_post_weld_images", -1)) == int(
            self.config.validation.expected_post_weld_images
        )

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def try_reuse(self, candidate: SampleCandidate) -> SampleProbe | None:
        connection = self.connection
        if not self.compatible or connection is None:
            return None

        row = connection.execute(
            "SELECT * FROM samples WHERE sample_id=? AND relpath=?",
            (candidate.sample_id, candidate.relpath),
        ).fetchone()
        if row is None:
            return None
        if _canonical(_candidate_metadata_payload(candidate)) != _canonical(
            _row_metadata_payload(row)
        ):
            return None

        old_assets = connection.execute(
            "SELECT * FROM assets WHERE sample_id=? ORDER BY kind, ordinal, relpath",
            (candidate.sample_id,),
        ).fetchall()
        old_signature = sorted(
            (
                str(asset["kind"]),
                int(asset["ordinal"]),
                str(asset["relpath"]),
                int(asset["size_bytes"]),
                int(asset["mtime_ns"]),
            )
            for asset in old_assets
        )
        live_signature = _live_asset_signature(candidate, self.config.dataset_root)
        if live_signature is None or live_signature != old_signature:
            return None
        if self.config.scan.compute_sha256 and any(not asset["sha256"] for asset in old_assets):
            return None

        assets: list[AssetProbe] = []
        try:
            for asset in old_assets:
                metadata = json.loads(asset["metadata_json"] or "{}")
                assets.append(
                    AssetProbe(
                        asset_id=str(asset["asset_id"]),
                        sample_id=candidate.sample_id,
                        kind=AssetKind(str(asset["kind"])),
                        path=safe_join(self.config.dataset_root, str(asset["relpath"])),
                        relpath=str(asset["relpath"]),
                        ordinal=int(asset["ordinal"]),
                        size_bytes=int(asset["size_bytes"]),
                        mtime_ns=int(asset["mtime_ns"]),
                        status=HealthStatus(str(asset["status"])),
                        metadata=metadata,
                        sha256=str(asset["sha256"]) if asset["sha256"] else None,
                    )
                )
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        issues: list[Issue] = []
        issue_rows = connection.execute(
            "SELECT * FROM issues WHERE sample_id=? ORDER BY issue_id",
            (candidate.sample_id,),
        ).fetchall()
        try:
            for issue in issue_rows:
                details = json.loads(issue["details_json"] or "{}")
                issues.append(
                    Issue(
                        severity=Severity(str(issue["severity"])),
                        code=str(issue["code"]),
                        message=str(issue["message"]),
                        sample_id=candidate.sample_id,
                        relpath=str(issue["relpath"]) if issue["relpath"] is not None else None,
                        details=details,
                    )
                )
            health = HealthStatus(str(row["health_status"]))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        return SampleProbe(
            candidate=candidate,
            assets=assets,
            issues=issues,
            health_status=health,
            total_bytes=int(row["total_bytes"]),
            image_count=int(row["image_count"]),
            primary_video_relpath=row["primary_video_relpath"],
            primary_audio_relpath=row["primary_audio_relpath"],
            primary_sensor_relpath=row["primary_sensor_relpath"],
        )
