from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssetKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SENSOR = "sensor"
    IMAGE = "image"
    OTHER = "other"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class HealthStatus(StrEnum):
    UNPROBED = "unprobed"
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class ProbeMode(StrEnum):
    NONE = "none"
    LIGHT = "light"
    FULL = "full"


class ManifestMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    category_raw: str | None = None
    category: str | None = None
    weld_type: str | None = None
    thickness_mm: float | None = None
    steel_type: str | None = None
    current_a: float | None = None
    voltage_v: float | None = None
    gas_bar: float | None = None
    robot_speed_cpm: float | None = None
    split: str | None = None
    source_manifest: str | None = None
    source_row: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SampleCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sample_id: str
    session_id: str
    sample_path: Path
    relpath: str
    metadata: ManifestMetadata = Field(default_factory=ManifestMetadata)
    discovered_by: list[str] = Field(default_factory=list)


class AssetProbe(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    asset_id: str
    sample_id: str
    kind: AssetKind
    path: Path
    relpath: str
    ordinal: int = 0
    size_bytes: int = 0
    mtime_ns: int = 0
    status: HealthStatus = HealthStatus.UNPROBED
    metadata: dict[str, Any] = Field(default_factory=dict)
    sha256: str | None = None


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str
    sample_id: str | None = None
    relpath: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SampleProbe(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate: SampleCandidate
    assets: list[AssetProbe] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    health_status: HealthStatus = HealthStatus.UNPROBED
    total_bytes: int = 0
    image_count: int = 0
    primary_video_relpath: str | None = None
    primary_audio_relpath: str | None = None
    primary_sensor_relpath: str | None = None
