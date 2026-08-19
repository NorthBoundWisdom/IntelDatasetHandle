from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..domain.models import Severity


class ValidationFinding(BaseModel):
    severity: Severity
    code: str
    message: str
    sample_id: str | None = None
    relpath: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    target_key: str | None = None
    disposition: str | None = None
    disposition_note: str | None = None
    active: bool = True


class ValidationReport(BaseModel):
    generated_at: str
    index_path: str
    dataset_root: str
    passed: bool
    summary: dict[str, Any]
    findings: list[ValidationFinding]

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "severity",
                    "code",
                    "sample_id",
                    "relpath",
                    "message",
                    "details_json",
                    "target_key",
                    "disposition",
                    "disposition_note",
                    "active",
                ],
            )
            writer.writeheader()
            for finding in self.findings:
                writer.writerow(
                    {
                        "severity": finding.severity.value,
                        "code": finding.code,
                        "sample_id": finding.sample_id,
                        "relpath": finding.relpath,
                        "message": finding.message,
                        "details_json": json.dumps(
                            finding.details, ensure_ascii=False, default=str
                        ),
                        "target_key": finding.target_key,
                        "disposition": finding.disposition,
                        "disposition_note": finding.disposition_note,
                        "active": finding.active,
                    }
                )
        return path
