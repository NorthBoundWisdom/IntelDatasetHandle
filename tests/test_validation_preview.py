from __future__ import annotations

from pathlib import Path

from weld_data_workbench.annotations import AnnotationStore, issue_target_key
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.previews.generator import PreviewGenerator
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture
from weld_data_workbench.validation.checks import run_validation


def test_validation_report(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    report = run_validation(config)
    assert report.passed
    assert (config.reports_dir / "validation.json").exists()
    assert (config.reports_dir / "validation.csv").exists()
    codes = {finding.code for finding in report.findings}
    assert "observed_audio_sample_rate" in codes
    assert "defect_in_training_split" not in codes


def test_preview_generation(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    sample = repository.list_samples(limit=1)[0]
    bundle = PreviewGenerator(config, repository).generate(sample["sample_id"])
    assert bundle.video_contact_sheet_url
    assert bundle.audio_waveform_url
    assert bundle.audio_spectrogram_url
    assert bundle.sensor_plot_url
    assert len(bundle.image_thumbnail_urls) == 5
    assert all(Path(path).exists() for path in bundle.generated_files)


def test_validation_keeps_ignored_source_issues_but_marks_them_inactive(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_real_schema_fixture(raw)
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)
    repository = DatasetRepository(config.index_path, config.dataset_root)

    source_issues = [
        issue
        for issue in repository.issues()
        if issue["code"] in {"missing_image", "unexpected_image_count"}
    ]
    assert len(source_issues) == 2

    before = run_validation(config, repository)
    assert all(
        finding.active
        for finding in before.findings
        if finding.code in {"missing_image", "unexpected_image_count"}
    )

    annotations = AnnotationStore(workspace / "overlays" / "annotations.sqlite3")
    for issue in source_issues:
        target_key = issue_target_key(
            str(issue["sample_id"]),
            str(issue["code"]),
            relpath=issue.get("relpath"),
            message=str(issue["message"]),
        )
        annotations.upsert(
            target_type="issue",
            target_key=target_key,
            sample_id=str(issue["sample_id"]),
            disposition="ignored",
            note="Confirmed omission in the upstream dataset; no source bytes were synthesized.",
            updated_by="test",
        )

    after = run_validation(config, repository)
    ignored = [
        finding
        for finding in after.findings
        if finding.code in {"missing_image", "unexpected_image_count"}
    ]
    assert len(ignored) == 2
    assert all(not finding.active for finding in ignored)
    assert all(finding.disposition == "ignored" for finding in ignored)
    assert all(finding.disposition_note for finding in ignored)
    assert after.summary["active_validation_findings_by_severity"]["error"] == (
        before.summary["active_validation_findings_by_severity"]["error"] - 1
    )
    assert after.summary["suppressed_validation_findings"] == 2
