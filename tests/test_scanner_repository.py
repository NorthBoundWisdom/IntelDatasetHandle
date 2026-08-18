from __future__ import annotations

from weld_data_workbench.index.repository import DatasetRepository


def test_index_summary(indexed_workspace) -> None:
    config, summary = indexed_workspace
    assert summary.sample_count == 14
    assert summary.asset_count == 14 * 8  # video + audio + sensor + five images
    assert summary.error_count == 0
    assert config.index_path.exists()


def test_repository_queries(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    stats = repository.stats()
    assert stats["total_samples"] == 14
    assert stats["total_sessions"] > 0
    assert stats["audio_sample_rates_hz"] == {"16000": 14}

    good_train = repository.list_samples(category="Good", split="train", limit=100)
    assert len(good_train) == 4
    detail = repository.get_sample(good_train[0]["sample_id"])
    assert detail is not None
    assert len(detail["assets"]) == 8
    assert len(detail["image_urls"]) == 5
    assert detail["primary_video_url"].startswith("file:")
    assert detail["issues"] == []
