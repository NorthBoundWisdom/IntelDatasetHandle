from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import __version__
from ..config import AppConfig
from ..domain.models import Issue, Severity
from ..io.discovery import discover_dataset
from ..io.paths import relative_posix
from ..io.probe import probe_sample
from .database import (
    connect_database,
    initialize_database,
    insert_issue,
    insert_probe,
    set_meta,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BuildSummary:
    index_path: Path
    sample_count: int
    asset_count: int
    issue_count: int
    error_count: int
    warning_count: int
    manifest_path: Path | None
    discovery_notes: list[str]


ProgressCallback = Callable[[int, int, str], None]


class IndexBuilder:
    def __init__(self, config: AppConfig):
        self.config = config

    def _temporary_path(self) -> Path:
        return self.config.index_path.with_name(self.config.index_path.name + ".building")

    def build(
        self,
        *,
        workers: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> BuildSummary:
        self.config.ensure_workspace_dirs()
        discovery = discover_dataset(self.config)
        total = len(discovery.candidates)

        temporary = self._temporary_path()
        for suffix in ("", "-wal", "-shm"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)

        connection = connect_database(temporary)
        initialize_database(connection)
        set_meta(connection, "schema_version", self.config.schema_version)
        set_meta(connection, "code_version", __version__)
        set_meta(connection, "dataset_root", self.config.dataset_root.as_posix())
        set_meta(connection, "workspace_root", self.config.workspace_root.as_posix())
        set_meta(connection, "created_at", utc_now_iso())
        set_meta(connection, "probe_mode", self.config.scan.probe_mode)
        set_meta(connection, "discovery_notes", discovery.notes)

        manifest_path: Path | None = None
        if discovery.manifest is not None:
            manifest_path = discovery.manifest.path
            try:
                manifest_relpath = relative_posix(manifest_path, self.config.dataset_root)
            except ValueError:
                manifest_relpath = manifest_path.as_posix()
            set_meta(connection, "manifest_path", manifest_relpath)
            set_meta(connection, "manifest_score", discovery.manifest.score)
            set_meta(connection, "manifest_columns", sorted(discovery.manifest.matched_columns))
            set_meta(connection, "manifest_rows", len(discovery.manifest.dataframe))
        else:
            insert_issue(
                connection,
                Issue(
                    severity=Severity.WARNING,
                    code="manifest_not_found",
                    message="No manifest matching the expected schema was found",
                    details={"notes": discovery.notes},
                ),
            )

        if total == 0:
            insert_issue(
                connection,
                Issue(
                    severity=Severity.ERROR,
                    code="no_samples_discovered",
                    message="No candidate sample directories were discovered",
                ),
            )

        completed = 0
        worker_count = workers or self.config.scan.workers
        futures: dict[Future, str] = {}

        try:
            with ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="weld-probe"
            ) as executor:
                for candidate in discovery.candidates:
                    futures[executor.submit(probe_sample, candidate, self.config)] = (
                        candidate.relpath
                    )

                for future in as_completed(futures):
                    relpath = futures[future]
                    try:
                        probe = future.result()
                    except (
                        Exception
                    ) as exc:  # isolate a programmer/decoder failure to one candidate
                        logger.exception("Unhandled probe failure for %s", relpath)
                        insert_issue(
                            connection,
                            Issue(
                                severity=Severity.ERROR,
                                code="unhandled_probe_exception",
                                message=str(exc),
                                relpath=relpath,
                                details={"exception_type": type(exc).__name__},
                            ),
                        )
                    else:
                        insert_probe(connection, probe)

                    completed += 1
                    if completed % 100 == 0:
                        connection.commit()
                    if progress:
                        progress(completed, total, relpath)

            set_meta(connection, "completed_at", utc_now_iso())
            set_meta(
                connection,
                "sample_count",
                connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0],
            )
            set_meta(
                connection,
                "asset_count",
                connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()

            # Remove old sidecar files before atomic replacement.
            for suffix in ("-wal", "-shm"):
                Path(str(self.config.index_path) + suffix).unlink(missing_ok=True)
            os.replace(temporary, self.config.index_path)
        except Exception:
            connection.close()
            for suffix in ("", "-wal", "-shm"):
                Path(str(temporary) + suffix).unlink(missing_ok=True)
            raise

        final = connect_database(self.config.index_path, read_only=True)
        sample_count = int(final.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
        asset_count = int(final.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
        issue_count = int(final.execute("SELECT COUNT(*) FROM issues").fetchone()[0])
        error_count = int(
            final.execute("SELECT COUNT(*) FROM issues WHERE severity='error'").fetchone()[0]
        )
        warning_count = int(
            final.execute("SELECT COUNT(*) FROM issues WHERE severity='warning'").fetchone()[0]
        )
        final.close()

        summary = BuildSummary(
            index_path=self.config.index_path,
            sample_count=sample_count,
            asset_count=asset_count,
            issue_count=issue_count,
            error_count=error_count,
            warning_count=warning_count,
            manifest_path=manifest_path,
            discovery_notes=discovery.notes,
        )
        logger.info("Index build summary: %s", json.dumps(asdict(summary), default=str))
        return summary
