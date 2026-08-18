from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    index_path: str
    dataset_root: str
    sample_count: int


class SamplePage(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class PreviewResponse(BaseModel):
    sample_id: str
    bundle: dict[str, Any]
