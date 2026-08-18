from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import AppConfig
from ..index.repository import DatasetRepository
from .audio import extract_audio_features
from .images import extract_image_features
from .sensor import extract_sensor_features
from .video import extract_video_features


@dataclass(slots=True)
class FeatureExtractionSummary:
    output_path: Path
    samples_requested: int
    samples_completed: int
    samples_failed: int
    feature_columns: int


ProgressCallback = Callable[[int, int, str], None]


class FeatureExtractor:
    def __init__(self, config: AppConfig, repository: DatasetRepository | None = None):
        self.config = config
        self.repository = repository or DatasetRepository(config.index_path, config.dataset_root)

    def _extract_one(self, sample_id: str, modalities: set[str]) -> dict[str, object]:
        sample = self.repository.get_sample(sample_id)
        if sample is None:
            return {"sample_id": sample_id, "feature_error": "sample_not_found"}

        row: dict[str, object] = {
            "sample_id": sample_id,
            "session_id": sample.get("session_id"),
            "relpath": sample.get("relpath"),
            "category": sample.get("category"),
            "category_raw": sample.get("category_raw"),
            "is_good": sample.get("is_good"),
            "split": sample.get("split"),
            "weld_type": sample.get("weld_type"),
            "thickness_mm": sample.get("thickness_mm"),
            "steel_type": sample.get("steel_type"),
            "current_a": sample.get("current_a"),
            "voltage_v": sample.get("voltage_v"),
            "gas_bar": sample.get("gas_bar"),
            "robot_speed_cpm": sample.get("robot_speed_cpm"),
        }
        errors: dict[str, str] = {}
        assets = sample.get("assets", [])

        def paths(kind: str) -> list[Path]:
            return [Path(asset["absolute_path"]) for asset in assets if asset["kind"] == kind]

        if "audio" in modalities:
            audio_paths = paths("audio")
            if audio_paths:
                try:
                    row.update(extract_audio_features(audio_paths[0]))
                except Exception as exc:
                    errors["audio"] = str(exc)
            else:
                errors["audio"] = "missing"

        if "video" in modalities:
            video_paths = paths("video")
            if video_paths:
                try:
                    row.update(extract_video_features(video_paths[0]))
                except Exception as exc:
                    errors["video"] = str(exc)
            else:
                errors["video"] = "missing"

        if "sensor" in modalities:
            sensor_paths = paths("sensor")
            if sensor_paths:
                try:
                    row.update(extract_sensor_features(sensor_paths[0]))
                except Exception as exc:
                    errors["sensor"] = str(exc)
            else:
                errors["sensor"] = "missing"

        if "image" in modalities or "images" in modalities:
            image_paths = paths("image")
            if image_paths:
                try:
                    row.update(extract_image_features(image_paths))
                except Exception as exc:
                    errors["image"] = str(exc)
            else:
                errors["image"] = "missing"

        row["feature_error"] = json.dumps(errors, ensure_ascii=False) if errors else None
        return row

    def extract(
        self,
        output_path: Path,
        *,
        modalities: Iterable[str] = ("audio", "video", "sensor", "image"),
        split: str | None = None,
        category: str | None = None,
        limit: int | None = None,
        workers: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> FeatureExtractionSummary:
        selected = {item.casefold() for item in modalities}
        allowed = {"audio", "video", "sensor", "image", "images"}
        unknown = selected - allowed
        if unknown:
            raise ValueError(f"Unsupported modalities: {sorted(unknown)}")

        rows = list(
            self.repository.iter_samples(
                split=split,
                category=category,
                batch_size=500,
            )
        )
        if limit is not None:
            rows = rows[: max(limit, 0)]
        sample_ids = [str(row["sample_id"]) for row in rows]
        total = len(sample_ids)

        extracted: list[dict[str, object]] = []
        completed = 0
        worker_count = workers or self.config.scan.workers
        futures: dict[Future[dict[str, object]], str] = {}
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="weld-features"
        ) as executor:
            for sample_id in sample_ids:
                futures[executor.submit(self._extract_one, sample_id, selected)] = sample_id
            for future in as_completed(futures):
                sample_id = futures[future]
                try:
                    extracted.append(future.result())
                except Exception as exc:
                    extracted.append(
                        {
                            "sample_id": sample_id,
                            "feature_error": json.dumps({"unhandled": str(exc)}),
                        }
                    )
                completed += 1
                if progress:
                    progress(completed, total, sample_id)

        frame = pd.DataFrame(extracted).sort_values("sample_id") if extracted else pd.DataFrame()
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = output_path.suffix.casefold()
        if suffix == ".parquet":
            try:
                frame.to_parquet(output_path, index=False)
            except ImportError as exc:
                raise RuntimeError("Parquet export requires 'pip install -e .[parquet]'") from exc
        elif suffix in {".jsonl", ".ndjson"}:
            frame.to_json(output_path, orient="records", lines=True, force_ascii=False)
        else:
            frame.to_csv(output_path, index=False)

        failed = int(frame["feature_error"].notna().sum()) if "feature_error" in frame else 0
        return FeatureExtractionSummary(
            output_path=output_path,
            samples_requested=total,
            samples_completed=len(frame),
            samples_failed=failed,
            feature_columns=len(frame.columns),
        )
