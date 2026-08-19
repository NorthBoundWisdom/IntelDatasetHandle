from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from weld_data_workbench.features.cache import FeatureJobStore
from weld_data_workbench.features.pipeline import FeatureExtractor
from weld_data_workbench.sqlite_utils import closing_connection


def _reset_feature_cache(config) -> None:
    path = config.features_dir / "feature_jobs.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def test_feature_cache_reuses_unchanged_modalities(indexed_workspace, tmp_path: Path) -> None:
    config, _summary = indexed_workspace
    _reset_feature_cache(config)
    extractor = FeatureExtractor(config)

    first = extractor.extract(
        tmp_path / "first.csv",
        modalities=("audio", "sensor"),
        workers=2,
    )
    assert first.samples_completed == 14
    assert first.samples_failed == 0
    assert first.jobs_requested == 28
    assert first.jobs_executed == 28
    assert first.jobs_reused == 0
    assert first.jobs_failed == 0
    assert first.cache_path is not None and first.cache_path.exists()

    second = extractor.extract(
        tmp_path / "second.csv",
        modalities=("audio", "sensor"),
        workers=2,
    )
    assert second.jobs_requested == 28
    assert second.jobs_executed == 0
    assert second.jobs_reused == 28
    assert second.jobs_failed == 0


def test_feature_cache_invalidates_only_touched_modality(indexed_workspace, tmp_path: Path) -> None:
    config, _summary = indexed_workspace
    _reset_feature_cache(config)
    extractor = FeatureExtractor(config)
    extractor.extract(
        tmp_path / "before.csv",
        modalities=("audio", "sensor"),
        workers=2,
    )

    row = extractor.repository.list_samples(category="Good", split="train", limit=1)[0]
    sample = extractor.repository.get_sample(str(row["sample_id"]))
    assert sample is not None
    audio = next(asset for asset in sample["assets"] if asset["kind"] == "audio")
    audio_path = Path(audio["absolute_path"])
    original_stat = audio_path.stat()
    try:
        audio_path.touch()

        after = extractor.extract(
            tmp_path / "after.csv",
            modalities=("audio", "sensor"),
            workers=2,
        )
        assert after.jobs_requested == 28
        assert after.jobs_executed == 1
        assert after.jobs_reused == 27
        assert after.jobs_failed == 0
    finally:
        # `synthetic_root` is session-scoped. Restore the original metadata so this
        # cache test cannot influence snapshot/index tests that run later.
        os.utime(
            audio_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )


def test_feature_job_store_recovers_interrupted_jobs(tmp_path: Path) -> None:
    store = FeatureJobStore(tmp_path / "jobs.sqlite3")
    plan = store.plan(
        sample_id="sample-a",
        modality="audio",
        sample_fingerprint="fingerprint",
        extractor_name="test",
        extractor_version="v1",
        config={"window": 10},
    )
    store.mark_running(plan)

    recovered = store.recover_interrupted()
    assert recovered == 1
    result = store.result(plan)
    assert result.status == "pending"
    assert result.error == "interrupted_before_completion"
    assert result.attempts == 1

    # State is persisted, not tied to one Python object.
    reopened = FeatureJobStore(tmp_path / "jobs.sqlite3")
    assert reopened.result(plan).status == "pending"

    with closing_connection(sqlite3.connect(tmp_path / "jobs.sqlite3")) as connection:
        states = dict(connection.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"))
    assert states == {"pending": 1}
