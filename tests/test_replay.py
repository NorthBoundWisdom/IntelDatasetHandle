from __future__ import annotations

import pytest
from pydantic import ValidationError

from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.replay import (
    AnomalyEvent,
    DatasetReplayService,
    FeedbackVerdict,
    OperatorFeedbackEvent,
    ReplayEventType,
    ReplayPlan,
    event_schema_bundle,
)


def test_event_schemas_validate_reliability_and_feedback() -> None:
    event = AnomalyEvent(
        event_id="evt-1",
        sample_id="sample-1",
        model_id="baseline",
        anomaly_score=0.8,
        threshold=0.5,
        decision=True,
        modality_scores={"audio": 0.9},
        modality_available={"audio": True},
        modality_reliability={"audio": 0.95},
    )
    assert event.schema_version == 1
    assert event.decision is True

    feedback = OperatorFeedbackEvent(
        feedback_id="fb-1",
        anomaly_event_id=event.event_id,
        sample_id=event.sample_id,
        verdict=FeedbackVerdict.TRUE_POSITIVE,
        defect_labels=["porosity"],
    )
    assert feedback.verdict == FeedbackVerdict.TRUE_POSITIVE

    with pytest.raises(ValidationError):
        AnomalyEvent(
            event_id="evt-2",
            sample_id="sample-1",
            model_id="baseline",
            anomaly_score=0.2,
            modality_reliability={"video": 1.5},
        )

    schemas = event_schema_bundle()
    assert schemas["schema_version"] == 1
    assert "properties" in schemas["anomaly_event"]


def test_dataset_replay_plan_is_deterministic(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    service = DatasetReplayService(repository)
    sample_ids = [record["sample_id"] for record in repository.list_samples(limit=2)]

    plan = ReplayPlan(sample_ids=sample_ids, interval_seconds=0.25, repeat=2)
    first = service.plan(plan)
    second = service.plan(plan)

    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    assert len(first) == 12
    assert [item.sequence for item in first] == list(range(12))
    assert all(
        first[index].relative_time_s <= first[index + 1].relative_time_s
        for index in range(len(first) - 1)
    )
    assert first[0].event_type == ReplayEventType.SAMPLE_STARTED
    assert first[1].event_type == ReplayEventType.SAMPLE_PAYLOAD
    assert first[1].payload["assets"]

    with pytest.raises(KeyError):
        service.plan(ReplayPlan(sample_ids=["missing-sample"]))
