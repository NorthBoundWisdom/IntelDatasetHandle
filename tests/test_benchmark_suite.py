from __future__ import annotations

from pathlib import Path

import pytest

from weld_data_workbench.benchmark_suite import (
    BenchmarkSuiteOptions,
    main,
    run_benchmark_suite,
    write_benchmark_suite_report,
)


def test_benchmark_suite_runs_full_measurement_stack(
    indexed_workspace,
    tmp_path: Path,
) -> None:
    config, _summary = indexed_workspace
    options = BenchmarkSuiteOptions(
        repository_iterations=3,
        page_size=2,
        scratch_scan=True,
        preview_samples=1,
        feature_samples=1,
        api_requests=8,
        api_concurrency=2,
        workers=2,
        include_snapshot=False,
        keep_scratch=False,
    )

    report = run_benchmark_suite(
        config,
        options=options,
        scratch_root=tmp_path / "scratch-parent",
    )
    payload = report.to_dict()

    assert payload["schema_version"] == 1
    assert payload["base"]["snapshot_id"] is None
    assert payload["base"]["repository"]["iterations"] == 3
    assert payload["base"]["repository"]["page_size"] == 2

    scan = payload["scratch_scan"]
    assert scan["enabled"] is True
    assert scan["probe_mode"] == "light"
    assert scan["full_scan"]["summary"]["sample_count"] == 14
    assert scan["full_scan"]["summary"]["added_sample_count"] == 14
    assert scan["full_scan"]["summary"]["reused_sample_count"] == 0
    assert scan["no_op_incremental_scan"]["summary"]["sample_count"] == 14
    assert scan["no_op_incremental_scan"]["summary"]["added_sample_count"] == 0
    assert scan["no_op_incremental_scan"]["summary"]["reused_sample_count"] == 14
    assert scan["no_op_incremental_scan"]["summary"]["probed_sample_count"] == 0
    assert scan["no_op_reused_all_samples"] is True
    assert scan["full_scan"]["samples_per_s"] > 0
    assert scan["no_op_incremental_scan"]["samples_per_s"] > 0

    previews = payload["previews"]
    assert previews["enabled"] is True
    assert len(previews["selected_samples"]) == 1
    for modality in ("video", "audio", "sensor", "image"):
        stage = previews["modality_generation"][modality]
        assert stage["samples_completed"] == 1
        assert stage["latency"]["count"] == 1
        assert stage["files_written"] > 0
        assert stage["warnings"] == []
    assert previews["bundle_generation"]["cold"]["latency"]["count"] == 1
    assert previews["bundle_generation"]["warm_cache"]["latency"]["count"] == 1
    assert previews["bundle_generation"]["cold"]["generated_files"] > 0
    assert previews["bundle_generation"]["warm_cache"]["generated_files"] > 0

    features = payload["features"]
    assert features["enabled"] is True
    assert features["requested_samples"] == 1
    assert features["workers"] == 2
    for modality in ("video", "audio", "sensor", "image"):
        stage = features["modalities"][modality]
        assert stage["cold"]["summary"]["samples_requested"] == 1
        assert stage["cold"]["summary"]["samples_completed"] == 1
        assert stage["cold"]["summary"]["jobs_executed"] == 1
        assert stage["cold"]["summary"]["jobs_failed"] == 0
        assert stage["warm_cache"]["summary"]["samples_requested"] == 1
        assert stage["warm_cache"]["summary"]["jobs_reused"] == 1
        assert stage["warm_cache"]["summary"]["jobs_executed"] == 0
        assert stage["cold"]["samples_per_s"] > 0
        assert stage["warm_cache"]["samples_per_s"] > 0

    api = payload["api"]
    assert api["enabled"] is True
    assert api["transport"] == "httpx.ASGITransport"
    assert api["requests"] == 8
    assert api["concurrency"] == 2
    assert api["status_counts"] == {"200": 8}
    assert api["latency"]["count"] == 8
    assert api["requests_per_s"] > 0
    assert api["successful_requests_per_s"] > 0

    assert report.warnings == []
    scratch_path = Path(payload["scratch"]["path"])
    assert payload["scratch"]["retained"] is False
    assert not scratch_path.exists()


def test_benchmark_suite_can_retain_scratch_and_write_json(
    indexed_workspace,
    tmp_path: Path,
) -> None:
    config, _summary = indexed_workspace
    options = BenchmarkSuiteOptions(
        repository_iterations=1,
        page_size=1,
        scratch_scan=False,
        preview_samples=0,
        feature_samples=0,
        api_requests=0,
        api_concurrency=1,
        workers=1,
        include_snapshot=False,
        keep_scratch=True,
    )

    report = run_benchmark_suite(
        config,
        options=options,
        scratch_root=tmp_path / "scratch-parent",
    )
    payload = report.to_dict()

    assert payload["scratch_scan"] == {
        "enabled": False,
        "reason": "scratch_scan option disabled",
    }
    assert payload["previews"]["enabled"] is False
    assert payload["previews"]["reason"] == "no samples selected"
    assert payload["features"]["enabled"] is False
    assert "feature sample limit is zero" in payload["features"]["reason"]
    assert payload["api"] == {
        "enabled": False,
        "reason": "api_requests is zero",
        "requests": 0,
    }

    scratch_path = Path(payload["scratch"]["path"])
    assert payload["scratch"]["retained"] is True
    assert scratch_path.is_dir()

    output = tmp_path / "reports" / "benchmark-suite.json"
    written = write_benchmark_suite_report(report, output)
    assert written == output.resolve()
    text = written.read_text(encoding="utf-8")
    assert '"schema_version": 1' in text
    assert '"scratch_scan"' in text


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository_iterations", 0, "repository_iterations"),
        ("page_size", 0, "page_size"),
        ("preview_samples", -1, "preview_samples"),
        ("feature_samples", -1, "feature_samples"),
        ("api_requests", -1, "api_requests"),
        ("api_concurrency", 0, "api_concurrency"),
        ("workers", 0, "workers"),
    ],
)
def test_benchmark_suite_options_validate_bounds(
    field: str,
    value: int,
    message: str,
) -> None:
    kwargs = {field: value}
    options = BenchmarkSuiteOptions(**kwargs)
    with pytest.raises(ValueError, match=message):
        options.validate()


def test_benchmark_suite_module_cli_writes_report(
    indexed_workspace,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, _summary = indexed_workspace
    output = tmp_path / "cli-benchmark-suite.json"
    exit_code = main(
        [
            "--workspace",
            str(config.workspace_root),
            "--output",
            str(output),
            "--repository-iterations",
            "1",
            "--page-size",
            "1",
            "--preview-samples",
            "0",
            "--feature-samples",
            "0",
            "--api-requests",
            "0",
            "--workers",
            "1",
            "--no-snapshot",
        ]
    )
    assert exit_code == 0
    assert output.is_file()
    captured = capsys.readouterr().out
    assert '"output"' in captured
    assert '"scratch_scan_enabled": false' in captured
