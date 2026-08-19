from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .index.repository import DatasetRepository

EVENT_SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


class FeedbackVerdict(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    TRUE_NEGATIVE = "true_negative"
    FALSE_NEGATIVE = "false_negative"
    UNCERTAIN = "uncertain"


class ReplayEventType(StrEnum):
    SAMPLE_STARTED = "sample_started"
    SAMPLE_PAYLOAD = "sample_payload"
    SAMPLE_FINISHED = "sample_finished"


class AnomalyEvent(BaseModel):
    schema_version: Literal[1] = EVENT_SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=200)
    sample_id: str = Field(min_length=1, max_length=200)
    emitted_at: datetime = Field(default_factory=utc_now)
    model_id: str = Field(min_length=1, max_length=200)
    anomaly_score: float
    threshold: float | None = None
    decision: bool | None = None
    modality_scores: dict[str, float | None] = Field(default_factory=dict)
    modality_available: dict[str, bool] = Field(default_factory=dict)
    modality_reliability: dict[str, float] = Field(default_factory=dict)
    dataset_snapshot_id: str | None = None
    split_artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("modality_reliability")
    @classmethod
    def validate_reliability(cls, value: dict[str, float]) -> dict[str, float]:
        invalid = {
            key: score
            for key, score in value.items()
            if not math.isfinite(score) or score < 0.0 or score > 1.0
        }
        if invalid:
            raise ValueError(f"modality_reliability must be within [0, 1]: {invalid}")
        return value


class OperatorFeedbackEvent(BaseModel):
    schema_version: Literal[1] = EVENT_SCHEMA_VERSION
    feedback_id: str = Field(min_length=1, max_length=200)
    anomaly_event_id: str = Field(min_length=1, max_length=200)
    sample_id: str = Field(min_length=1, max_length=200)
    emitted_at: datetime = Field(default_factory=utc_now)
    verdict: FeedbackVerdict
    defect_labels: list[str] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=10_000)
    operator_id: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayPlan(BaseModel):
    sample_ids: list[str] = Field(min_length=1, max_length=10_000)
    interval_seconds: float = Field(default=1.0, ge=0.0, le=86_400.0)
    repeat: int = Field(default=1, ge=1, le=1000)
    include_assets: bool = True


class ReplayEvent(BaseModel):
    schema_version: Literal[1] = EVENT_SCHEMA_VERSION
    event_id: str
    event_type: ReplayEventType
    sample_id: str
    sequence: int = Field(ge=0)
    cycle: int = Field(ge=0)
    relative_time_s: float = Field(ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)


def event_schema_bundle() -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "anomaly_event": AnomalyEvent.model_json_schema(),
        "operator_feedback_event": OperatorFeedbackEvent.model_json_schema(),
        "replay_plan": ReplayPlan.model_json_schema(),
        "replay_event": ReplayEvent.model_json_schema(),
    }


class DatasetReplayService:
    """Build deterministic replay envelopes without assuming any transport."""

    def __init__(self, repository: DatasetRepository):
        self.repository = repository

    @staticmethod
    def _sample_payload(sample: dict[str, Any], *, include_assets: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": sample.get("session_id"),
            "category": sample.get("category"),
            "split": sample.get("split"),
            "weld_type": sample.get("weld_type"),
            "thickness_mm": sample.get("thickness_mm"),
            "steel_type": sample.get("steel_type"),
            "current_a": sample.get("current_a"),
            "voltage_v": sample.get("voltage_v"),
            "gas_bar": sample.get("gas_bar"),
            "robot_speed_cpm": sample.get("robot_speed_cpm"),
            "health_status": sample.get("health_status"),
        }
        if include_assets:
            payload["assets"] = [
                {
                    "asset_id": asset.get("asset_id"),
                    "kind": asset.get("kind"),
                    "ordinal": asset.get("ordinal"),
                    "relpath": asset.get("relpath"),
                    "status": asset.get("status"),
                    "size_bytes": asset.get("size_bytes"),
                }
                for asset in sample.get("assets", [])
            ]
        return payload

    def plan(self, plan: ReplayPlan) -> list[ReplayEvent]:
        events: list[ReplayEvent] = []
        sequence = 0
        relative_time = 0.0

        for cycle in range(plan.repeat):
            for sample_id in plan.sample_ids:
                sample = self.repository.get_sample(sample_id)
                if sample is None:
                    raise KeyError(f"Unknown sample: {sample_id}")
                payload = self._sample_payload(sample, include_assets=plan.include_assets)
                prefix = f"replay:{cycle}:{sequence}:{sample_id}"

                events.append(
                    ReplayEvent(
                        event_id=f"{prefix}:started",
                        event_type=ReplayEventType.SAMPLE_STARTED,
                        sample_id=sample_id,
                        sequence=sequence,
                        cycle=cycle,
                        relative_time_s=relative_time,
                        payload={},
                    )
                )
                sequence += 1
                events.append(
                    ReplayEvent(
                        event_id=f"{prefix}:payload",
                        event_type=ReplayEventType.SAMPLE_PAYLOAD,
                        sample_id=sample_id,
                        sequence=sequence,
                        cycle=cycle,
                        relative_time_s=relative_time,
                        payload=payload,
                    )
                )
                sequence += 1
                events.append(
                    ReplayEvent(
                        event_id=f"{prefix}:finished",
                        event_type=ReplayEventType.SAMPLE_FINISHED,
                        sample_id=sample_id,
                        sequence=sequence,
                        cycle=cycle,
                        relative_time_s=relative_time + plan.interval_seconds,
                        payload={},
                    )
                )
                sequence += 1
                relative_time += plan.interval_seconds
        return events
