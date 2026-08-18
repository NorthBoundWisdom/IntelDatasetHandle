from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from ..errors import IndexNotFoundError
from ..io.paths import safe_join
from .database import connect_database


class DatasetRepository:
    SORT_COLUMNS: ClassVar[dict[str, str]] = {
        "sample_id": "sample_id",
        "session_id": "session_id",
        "category": "category",
        "split": "split",
        "health": "health_status",
        "bytes": "total_bytes",
        "relpath": "relpath",
    }

    def __init__(self, index_path: Path, dataset_root: Path | None = None):
        self.index_path = index_path.expanduser().resolve()
        if not self.index_path.exists():
            raise IndexNotFoundError(f"Index not found: {self.index_path}. Run 'weldtool scan'.")
        self._dataset_root_override = dataset_root.expanduser().resolve() if dataset_root else None

    def _connect(self) -> sqlite3.Connection:
        return connect_database(self.index_path, read_only=True)

    def meta(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            value = row["value"]
            try:
                result[row["key"]] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                result[row["key"]] = value
        return result

    @property
    def dataset_root(self) -> Path:
        if self._dataset_root_override is not None:
            return self._dataset_root_override
        raw = self.meta().get("dataset_root")
        if not raw:
            raise IndexNotFoundError("Index metadata does not contain dataset_root")
        return Path(str(raw)).expanduser().resolve()

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _parse_json_fields(record: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
        for field in fields:
            raw = record.get(field)
            if raw is None:
                continue
            with suppress(TypeError, json.JSONDecodeError):
                record[field] = json.loads(raw)
        return record

    def count_samples(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
    ) -> int:
        where, params = self._build_filters(
            query=query, category=category, split=split, health=health
        )
        sql = "SELECT COUNT(*) FROM samples" + where
        with self._connect() as connection:
            return int(connection.execute(sql, params).fetchone()[0])

    @staticmethod
    def _build_filters(
        *,
        query: str | None,
        category: str | None,
        split: str | None,
        health: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            like = f"%{query}%"
            clauses.append(
                "(sample_id LIKE ? OR session_id LIKE ? OR relpath LIKE ? OR category LIKE ? OR weld_type LIKE ? OR steel_type LIKE ?)"
            )
            params.extend([like] * 6)
        if category and category.casefold() not in {"all", "*"}:
            clauses.append("category = ?")
            params.append(category)
        if split and split.casefold() not in {"all", "*"}:
            clauses.append("split = ?")
            params.append(split)
        if health and health.casefold() not in {"all", "*"}:
            clauses.append("health_status = ?")
            params.append(health)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    def list_samples(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "relpath",
        descending: bool = False,
    ) -> list[dict[str, Any]]:
        sort_column = self.SORT_COLUMNS.get(sort_by)
        if sort_column is None:
            raise ValueError(f"Unsupported sort column: {sort_by}")
        direction = "DESC" if descending else "ASC"
        where, params = self._build_filters(
            query=query, category=category, split=split, health=health
        )
        sql = f"""
            SELECT
                sample_id, session_id, relpath, category_raw, category, is_good,
                split, weld_type, thickness_mm, steel_type, current_a, voltage_v,
                gas_bar, robot_speed_cpm, health_status, total_bytes, image_count,
                primary_video_relpath, primary_audio_relpath, primary_sensor_relpath,
                scanned_at
            FROM samples
            {where}
            ORDER BY {sort_column} {direction}, sample_id ASC
            LIMIT ? OFFSET ?
        """
        params.extend([max(0, min(limit, 10_000)), max(0, offset)])
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row_dict(row) for row in rows]

    def get_sample(self, sample_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
            ).fetchone()
            if row is None:
                return None
            assets = connection.execute(
                "SELECT * FROM assets WHERE sample_id = ? ORDER BY kind, ordinal, relpath",
                (sample_id,),
            ).fetchall()
            issues = connection.execute(
                "SELECT * FROM issues WHERE sample_id = ? ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, issue_id",
                (sample_id,),
            ).fetchall()

        record = self._parse_json_fields(
            self._row_dict(row),
            ("manifest_raw_json", "discovered_by_json"),
        )
        root = self.dataset_root
        record["absolute_path"] = str(safe_join(root, record["relpath"]))
        try:
            record["file_url"] = safe_join(root, record["relpath"]).as_uri()
        except ValueError:
            record["file_url"] = None

        parsed_assets: list[dict[str, Any]] = []
        for asset_row in assets:
            asset = self._parse_json_fields(self._row_dict(asset_row), ("metadata_json",))
            absolute = safe_join(root, asset["relpath"])
            asset["absolute_path"] = str(absolute)
            asset["file_url"] = absolute.as_uri()
            parsed_assets.append(asset)
        record["assets"] = parsed_assets

        record["issues"] = [
            self._parse_json_fields(self._row_dict(issue_row), ("details_json",))
            for issue_row in issues
        ]
        record["image_urls"] = [
            asset["file_url"] for asset in parsed_assets if asset["kind"] == "image"
        ]

        for field, kind in (
            ("primary_video_url", "video"),
            ("primary_audio_url", "audio"),
            ("primary_sensor_url", "sensor"),
        ):
            matching = [asset for asset in parsed_assets if asset["kind"] == kind]
            record[field] = matching[0]["file_url"] if matching else None
        return record

    def iter_samples(self, *, batch_size: int = 500, **filters: Any) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            batch = self.list_samples(limit=batch_size, offset=offset, **filters)
            if not batch:
                break
            yield from batch
            offset += len(batch)

    def categories(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT category FROM samples WHERE category IS NOT NULL ORDER BY category"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def splits(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT split FROM samples WHERE split IS NOT NULL ORDER BY split"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            total_samples = int(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
            total_sessions = int(
                connection.execute("SELECT COUNT(DISTINCT session_id) FROM samples").fetchone()[0]
            )
            total_assets = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
            total_bytes = int(
                connection.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM assets").fetchone()[0]
            )
            total_issues = int(connection.execute("SELECT COUNT(*) FROM issues").fetchone()[0])

            def grouped(sql: str) -> dict[str, int]:
                return {
                    str(row[0] if row[0] is not None else "Unknown"): int(row[1])
                    for row in connection.execute(sql).fetchall()
                }

            by_category = grouped(
                "SELECT COALESCE(category, 'Unknown'), COUNT(*) FROM samples GROUP BY category ORDER BY COUNT(*) DESC"
            )
            by_split = grouped(
                "SELECT COALESCE(split, 'Unknown'), COUNT(*) FROM samples GROUP BY split ORDER BY split"
            )
            by_health = grouped(
                "SELECT health_status, COUNT(*) FROM samples GROUP BY health_status ORDER BY health_status"
            )
            assets_by_kind = grouped(
                "SELECT kind, COUNT(*) FROM assets GROUP BY kind ORDER BY kind"
            )
            issues_by_severity = grouped(
                "SELECT severity, COUNT(*) FROM issues GROUP BY severity ORDER BY severity"
            )
            top_issue_codes = [
                {"code": str(row[0]), "count": int(row[1])}
                for row in connection.execute(
                    "SELECT code, COUNT(*) FROM issues GROUP BY code ORDER BY COUNT(*) DESC, code LIMIT 20"
                ).fetchall()
            ]

            audio_rates: dict[str, int] = {}
            for row in connection.execute(
                "SELECT metadata_json FROM assets WHERE kind='audio' AND status != 'error'"
            ).fetchall():
                try:
                    metadata = json.loads(row[0])
                    rate = metadata.get("sample_rate_hz")
                except (TypeError, json.JSONDecodeError):
                    continue
                if rate:
                    audio_rates[str(rate)] = audio_rates.get(str(rate), 0) + 1

        return {
            "total_samples": total_samples,
            "total_sessions": total_sessions,
            "total_assets": total_assets,
            "total_bytes": total_bytes,
            "total_issues": total_issues,
            "by_category": by_category,
            "by_split": by_split,
            "by_health": by_health,
            "assets_by_kind": assets_by_kind,
            "issues_by_severity": issues_by_severity,
            "top_issue_codes": top_issue_codes,
            "audio_sample_rates_hz": audio_rates,
            "meta": self.meta(),
        }

    def issues(
        self,
        *,
        severity: str | None = None,
        code: str | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if code:
            clauses.append("code = ?")
            params.append(code)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(min(max(limit, 0), 100_000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM issues" + where + " ORDER BY issue_id LIMIT ?", params
            ).fetchall()
        return [self._parse_json_fields(self._row_dict(row), ("details_json",)) for row in rows]

    def resolve_asset(self, sample_id: str, kind: str, ordinal: int = 0) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT relpath FROM assets WHERE sample_id = ? AND kind = ? AND ordinal = ?",
                (sample_id, kind, ordinal),
            ).fetchone()
        if row is None:
            return None
        return safe_join(self.dataset_root, row[0])
