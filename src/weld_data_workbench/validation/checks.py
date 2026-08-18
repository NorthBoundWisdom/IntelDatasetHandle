from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..config import AppConfig
from ..domain.categories import CANONICAL_CATEGORIES
from ..domain.models import Severity
from ..index.database import connect_database
from ..index.repository import DatasetRepository
from .report import ValidationFinding, ValidationReport


def _finding(
    severity: Severity,
    code: str,
    message: str,
    *,
    sample_id: str | None = None,
    relpath: str | None = None,
    details: dict[str, Any] | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        severity=severity,
        code=code,
        message=message,
        sample_id=sample_id,
        relpath=relpath,
        details=details or {},
    )


def run_validation(
    config: AppConfig, repository: DatasetRepository | None = None
) -> ValidationReport:
    repo = repository or DatasetRepository(config.index_path, config.dataset_root)
    stats = repo.stats()
    findings: list[ValidationFinding] = []

    # Preserve all scanner issues in the exported validation report.
    for issue in repo.issues(limit=100_000):
        findings.append(
            _finding(
                Severity(issue["severity"]),
                issue["code"],
                issue["message"],
                sample_id=issue.get("sample_id"),
                relpath=issue.get("relpath"),
                details=issue.get("details_json") or {},
            )
        )

    if stats["total_samples"] == 0:
        findings.append(_finding(Severity.ERROR, "empty_index", "The index contains no samples"))

    categories = set(repo.categories())
    unknown_categories = sorted(categories - set(CANONICAL_CATEGORIES))
    if unknown_categories:
        findings.append(
            _finding(
                Severity.WARNING,
                "unknown_categories",
                "The index contains categories outside the public 12-category taxonomy",
                details={"categories": unknown_categories},
            )
        )

    expected_category_count = config.validation.expected_categories
    if expected_category_count and len(categories) != expected_category_count:
        findings.append(
            _finding(
                Severity.WARNING,
                "unexpected_category_count",
                f"Expected {expected_category_count} distinct categories, found {len(categories)}",
                details={"categories": sorted(categories)},
            )
        )

    with connect_database(config.index_path, read_only=True) as connection:
        if config.validation.enforce_train_good_only:
            rows = connection.execute(
                """
                SELECT sample_id, relpath, category, split
                FROM samples
                WHERE split = 'train' AND COALESCE(is_good, 0) = 0
                ORDER BY relpath
                """
            ).fetchall()
            for row in rows:
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "defect_in_training_split",
                        "The anomaly-detection protocol expects training samples to be Good only",
                        sample_id=row["sample_id"],
                        relpath=row["relpath"],
                        details={"category": row["category"], "split": row["split"]},
                    )
                )

        if config.validation.warn_on_unknown_split:
            rows = connection.execute(
                """
                SELECT sample_id, relpath, split
                FROM samples
                WHERE split IS NOT NULL AND split NOT IN ('train', 'validation', 'test')
                ORDER BY relpath
                """
            ).fetchall()
            for row in rows:
                findings.append(
                    _finding(
                        Severity.WARNING,
                        "unknown_split",
                        "Split is not one of train/validation/test",
                        sample_id=row["sample_id"],
                        relpath=row["relpath"],
                        details={"split": row["split"]},
                    )
                )

        leakage_rows = connection.execute(
            """
            SELECT session_id, GROUP_CONCAT(DISTINCT split) AS splits, COUNT(DISTINCT split) AS split_count
            FROM samples
            WHERE split IS NOT NULL
            GROUP BY session_id
            HAVING COUNT(DISTINCT split) > 1
            ORDER BY session_id
            """
        ).fetchall()
        if leakage_rows:
            findings.append(
                _finding(
                    Severity.WARNING,
                    "session_crosses_splits",
                    "Some session IDs occur in multiple splits; inspect whether this creates correlated leakage",
                    details={
                        "session_count": len(leakage_rows),
                        "examples": [
                            {"session_id": row["session_id"], "splits": row["splits"]}
                            for row in leakage_rows[:20]
                        ],
                    },
                )
            )

        duplicate_asset_rows = connection.execute(
            """
            SELECT relpath, COUNT(*) AS count
            FROM assets
            GROUP BY relpath
            HAVING COUNT(*) > 1
            ORDER BY count DESC, relpath
            """
        ).fetchall()
        if duplicate_asset_rows:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "asset_reused_by_multiple_samples",
                    "The same asset path is attached to multiple indexed samples",
                    details={
                        "examples": [dict(row) for row in duplicate_asset_rows[:20]],
                        "count": len(duplicate_asset_rows),
                    },
                )
            )

    audio_rates = stats.get("audio_sample_rates_hz", {})
    if len(audio_rates) > 1:
        findings.append(
            _finding(
                Severity.WARNING,
                "mixed_audio_sample_rates",
                "Audio assets use more than one sample rate; preprocessing must resample explicitly",
                details={"sample_rates_hz": audio_rates},
            )
        )
    elif len(audio_rates) == 1:
        rate = next(iter(audio_rates))
        findings.append(
            _finding(
                Severity.INFO,
                "observed_audio_sample_rate",
                f"Observed FLAC sample rate: {rate} Hz",
                details={"sample_rates_hz": audio_rates},
            )
        )

    severity_counts = {severity.value: 0 for severity in Severity}
    for finding in findings:
        severity_counts[finding.severity.value] += 1

    passed = severity_counts[Severity.ERROR.value] == 0
    report = ValidationReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        index_path=str(config.index_path),
        dataset_root=str(config.dataset_root),
        passed=passed,
        summary={
            **stats,
            "validation_findings_by_severity": severity_counts,
        },
        findings=findings,
    )
    report.write_json(config.reports_dir / "validation.json")
    report.write_csv(config.reports_dir / "validation.csv")
    return report
