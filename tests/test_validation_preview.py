from __future__ import annotations

from pathlib import Path

from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.previews.generator import PreviewGenerator
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
