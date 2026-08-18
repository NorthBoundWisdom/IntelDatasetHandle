from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import CONFIG_FILENAME, DEFAULT_INDEX_FILENAME, SCHEMA_VERSION
from .errors import ConfigurationError


class ScanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers: int = Field(default=8, ge=1, le=128)
    probe_mode: Literal["none", "light", "full"] = "light"
    follow_symlinks: bool = False
    include_hidden: bool = False
    compute_sha256: bool = False
    max_sensor_preview_rows: int = Field(default=50_000, ge=100)


class ManifestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_names: list[str] = Field(
        default_factory=lambda: [
            "manifest.csv",
            "dataset_manifest.csv",
            "annotations.csv",
            "metadata.csv",
        ]
    )
    max_search_depth: int = Field(default=3, ge=0, le=10)


class ValidationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_post_weld_images: int = Field(default=5, ge=0)
    expected_categories: int = Field(default=12, ge=0)
    warn_on_unknown_split: bool = True
    enforce_train_good_only: bool = True


class PreviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_frames: int = Field(default=5, ge=1, le=20)
    max_width: int = Field(default=1280, ge=320, le=4096)
    image_thumbnail_size: int = Field(default=512, ge=64, le=2048)
    audio_max_points: int = Field(default=30_000, ge=1_000)
    sensor_max_columns: int = Field(default=8, ge=1, le=64)
    sensor_max_rows: int = Field(default=20_000, ge=100)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    dataset_root: Path
    workspace_root: Path
    index_filename: str = DEFAULT_INDEX_FILENAME
    scan: ScanConfig = Field(default_factory=ScanConfig)
    manifest: ManifestConfig = Field(default_factory=ManifestConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)

    @field_validator("dataset_root", "workspace_root", mode="before")
    @classmethod
    def _expand_path(cls, value: Any) -> Path:
        return Path(value).expanduser().resolve()

    @field_validator("index_filename")
    @classmethod
    def _validate_index_filename(cls, value: str) -> str:
        if not value or Path(value).name != value:
            raise ValueError("index_filename must be a plain filename")
        return value

    @model_validator(mode="after")
    def _validate_schema(self) -> AppConfig:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported configuration schema {self.schema_version}; expected {SCHEMA_VERSION}"
            )
        return self

    @property
    def config_path(self) -> Path:
        return self.workspace_root / CONFIG_FILENAME

    @property
    def index_path(self) -> Path:
        return self.workspace_root / self.index_filename

    @property
    def reports_dir(self) -> Path:
        return self.workspace_root / "reports"

    @property
    def previews_dir(self) -> Path:
        return self.workspace_root / "previews"

    @property
    def features_dir(self) -> Path:
        return self.workspace_root / "features"

    @property
    def models_dir(self) -> Path:
        return self.workspace_root / "models"

    def ensure_workspace_dirs(self) -> None:
        for path in (
            self.workspace_root,
            self.reports_dir,
            self.previews_dir,
            self.features_dir,
            self.models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _config_to_yaml_data(config: AppConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    # JSON mode already serializes Path to strings.
    return data


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    destination = (path or config.config_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(_config_to_yaml_data(config), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return destination


def init_workspace(
    dataset_root: Path,
    workspace_root: Path,
    *,
    force: bool = False,
) -> AppConfig:
    dataset_root = dataset_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()

    if not dataset_root.exists():
        raise ConfigurationError(f"Dataset root does not exist: {dataset_root}")
    if not dataset_root.is_dir():
        raise ConfigurationError(f"Dataset root is not a directory: {dataset_root}")

    config_path = workspace_root / CONFIG_FILENAME
    if config_path.exists() and not force:
        raise ConfigurationError(
            f"Workspace already contains {CONFIG_FILENAME}: {config_path}. "
            "Use --force to overwrite only the configuration file."
        )

    config = AppConfig(dataset_root=dataset_root, workspace_root=workspace_root)
    config.ensure_workspace_dirs()
    save_config(config)
    return config


def resolve_config_path(workspace_or_config: Path) -> Path:
    candidate = workspace_or_config.expanduser().resolve()
    if candidate.is_dir():
        candidate = candidate / CONFIG_FILENAME
    return candidate


def load_config(workspace_or_config: Path) -> AppConfig:
    path = resolve_config_path(workspace_or_config)
    if not path.exists():
        raise ConfigurationError(f"Configuration not found: {path}. Run 'weldtool init' first.")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        config = AppConfig.model_validate(raw)
    except Exception as exc:  # pydantic/yaml provide useful nested context
        raise ConfigurationError(f"Invalid configuration {path}: {exc}") from exc

    config.ensure_workspace_dirs()
    return config
