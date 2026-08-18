from __future__ import annotations

import json
from pathlib import Path

from weld_data_workbench.benchmark import run_repository_benchmark, write_benchmark_report


def test_repository_benchmark_is_machine_readable(indexed_workspace, tmp_path: Path) -> None:
    config, _summary = indexed_workspace
    report = run_repository_benchmark(
        config,
        iterations=5,
        page_size=4,
        include_snapshot=True,
    )

    assert report.schema_version == 1
    assert report.snapshot_id
    assert report.dataset["samples"] == 14
    assert report.dataset["assets"] > 0
    assert report.dataset["index_size_bytes"] > 0
    assert report.repository["list_samples"]["count"] == 5
    assert report.repository["get_sample"]["count"] == 5
    assert report.repository["list_samples"]["p95_ms"] >= 0
    assert report.platform["python"]

    output = write_benchmark_report(report, tmp_path / "benchmark.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["snapshot_id"] == report.snapshot_id
    assert payload["dataset"]["samples"] == 14
