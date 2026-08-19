from __future__ import annotations

from pathlib import Path

import pytest

from weld_data_workbench.annotations import (
    AnnotationConflictError,
    AnnotationStore,
    issue_target_key,
)


def test_annotation_store_revision_history_and_filters(tmp_path: Path) -> None:
    store = AnnotationStore(tmp_path / "overlays" / "annotations.sqlite3")

    first = store.upsert(
        target_type="sample",
        target_key="sample-1",
        sample_id="sample-1",
        disposition="needs_review",
        note="check weld edge",
        tags=["edge", "edge", "manual"],
        updated_by="tester",
        expected_revision=0,
    )
    assert first.revision == 1
    assert first.tags == ("edge", "manual")
    assert store.get("sample", "sample-1") == first

    second = store.upsert(
        target_type="sample",
        target_key="sample-1",
        sample_id="sample-1",
        disposition="accepted",
        note="confirmed",
        tags=["manual"],
        updated_by="tester",
        expected_revision=1,
    )
    assert second.revision == 2
    assert second.created_at == first.created_at
    assert len(store.history("sample", "sample-1")) == 2
    assert [item.revision for item in store.list(sample_id="sample-1")] == [2]
    assert [item.revision for item in store.list(disposition="accepted")] == [2]

    with pytest.raises(AnnotationConflictError):
        store.upsert(
            target_type="sample",
            target_key="sample-1",
            sample_id="sample-1",
            disposition="resolved",
            expected_revision=1,
        )


def test_issue_target_key_and_validation(tmp_path: Path) -> None:
    key = issue_target_key("sample-1", "BAD_MEDIA", relpath="video.avi", message="decode")
    assert key == issue_target_key("sample-1", "BAD_MEDIA", relpath="video.avi", message="decode")
    assert key != issue_target_key("sample-1", "BAD_MEDIA", relpath="audio.flac")

    store = AnnotationStore(tmp_path / "annotations.sqlite3")
    issue = store.upsert(
        target_type="issue",
        target_key=key,
        sample_id="sample-1",
        disposition="ignored",
    )
    assert issue.target_type == "issue"
    assert store.list(target_type="issue")[0].target_key == key

    with pytest.raises(ValueError):
        store.upsert(
            target_type="other",
            target_key="x",
            sample_id="sample-1",
            disposition="open",
        )
    with pytest.raises(ValueError):
        store.list(disposition="not-a-state")
