from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pandas as pd
import soundfile as sf
from filelock import FileLock
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from scipy import signal

from ..config import AppConfig
from ..index.repository import DatasetRepository
from .cache import load_bundle, sample_cache_key

matplotlib.use("Agg")
from matplotlib import pyplot as plt


class PreviewBundle(BaseModel):
    sample_id: str
    cache_key: str
    output_dir: str
    video_poster_url: str | None = None
    video_contact_sheet_url: str | None = None
    audio_waveform_url: str | None = None
    audio_spectrogram_url: str | None = None
    sensor_plot_url: str | None = None
    image_thumbnail_urls: list[str] = Field(default_factory=list)
    generated_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _uri_or_none(path: Path | None) -> str | None:
    return path.as_uri() if path and path.exists() else None


def _resize_cv_frame(frame: np.ndarray, max_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    return cv2.resize(frame, (max_width, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)


def _extract_video_frames(path: Path, count: int, max_width: int) -> list[tuple[int, np.ndarray]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return []
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        capture.release()
        return []

    positions = np.linspace(0, max(total - 1, 0), num=count, dtype=int)
    frames: list[tuple[int, np.ndarray]] = []
    for position in positions:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
        ok, frame = capture.read()
        if ok and frame is not None and frame.size:
            frames.append((int(position), _resize_cv_frame(frame, max_width)))
    capture.release()
    return frames


def _write_video_previews(
    video_path: Path,
    output_dir: Path,
    *,
    count: int,
    max_width: int,
) -> tuple[Path | None, Path | None]:
    frames = _extract_video_frames(video_path, count, max_width)
    if not frames:
        return None, None

    middle = frames[len(frames) // 2][1]
    poster_path = output_dir / "video_poster.jpg"
    cv2.imwrite(str(poster_path), middle, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    pil_frames: list[Image.Image] = []
    for frame_index, frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 150, 28), fill=(0, 0, 0))
        draw.text((8, 7), f"frame {frame_index}", fill=(255, 255, 255))
        pil_frames.append(image)

    columns = min(3, len(pil_frames))
    rows = math.ceil(len(pil_frames) / columns)
    cell_width = max(image.width for image in pil_frames)
    cell_height = max(image.height for image in pil_frames)
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows))
    for index, image in enumerate(pil_frames):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(image, (x, y))

    sheet_path = output_dir / "video_contact_sheet.jpg"
    sheet.save(sheet_path, quality=88)
    return poster_path, sheet_path


def _load_audio_bounded(path: Path, max_seconds: float = 120.0) -> tuple[np.ndarray, int]:
    with sf.SoundFile(str(path)) as handle:
        frames = min(handle.frames, int(handle.samplerate * max_seconds))
        audio = handle.read(frames, dtype="float32", always_2d=True)
        sample_rate = int(handle.samplerate)
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    return mono.astype(np.float32, copy=False), sample_rate


def _write_audio_previews(
    audio_path: Path,
    output_dir: Path,
    *,
    max_points: int,
) -> tuple[Path | None, Path | None]:
    audio, sample_rate = _load_audio_bounded(audio_path)
    if audio.size == 0 or sample_rate <= 0:
        return None, None

    stride = max(1, math.ceil(audio.size / max_points))
    sampled = audio[::stride]
    time_axis = np.arange(sampled.size) * stride / sample_rate

    waveform_path = output_dir / "audio_waveform.png"
    figure = plt.figure(figsize=(12, 3.5), constrained_layout=True)
    axis = figure.add_subplot(111)
    axis.plot(time_axis, sampled, linewidth=0.6)
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Amplitude")
    axis.set_title(f"Audio waveform — {sample_rate} Hz")
    axis.grid(True, alpha=0.25)
    figure.savefig(waveform_path, dpi=140)
    plt.close(figure)

    analysis_audio = audio
    analysis_rate = sample_rate
    if sample_rate > 48_000:
        target_rate = 48_000
        target_count = max(1, round(audio.size * target_rate / sample_rate))
        analysis_audio = signal.resample(audio, target_count)
        analysis_rate = target_rate

    nperseg = min(2048, max(256, analysis_audio.size // 16))
    if analysis_audio.size < nperseg:
        return waveform_path, None

    frequencies, times, power = signal.spectrogram(
        analysis_audio,
        fs=analysis_rate,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        scaling="spectrum",
        mode="magnitude",
    )
    db = 20.0 * np.log10(power + 1e-8)

    spectrogram_path = output_dir / "audio_spectrogram.png"
    figure = plt.figure(figsize=(12, 4.5), constrained_layout=True)
    axis = figure.add_subplot(111)
    mesh = axis.pcolormesh(times, frequencies, db, shading="auto")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Frequency (Hz)")
    axis.set_title(f"Audio spectrogram — analysis rate {analysis_rate} Hz")
    figure.colorbar(mesh, ax=axis, label="Magnitude (dB)")
    figure.savefig(spectrogram_path, dpi=140)
    plt.close(figure)
    return waveform_path, spectrogram_path


def _write_sensor_preview(
    sensor_path: Path,
    output_dir: Path,
    *,
    max_columns: int,
    max_rows: int,
) -> Path | None:
    frame = pd.read_csv(sensor_path, sep=None, engine="python", nrows=max_rows)
    numeric = frame.select_dtypes(include=["number"])
    if numeric.empty:
        return None

    # Prefer a plausible time column for the x axis; otherwise use row index.
    time_candidates = [
        column
        for column in numeric.columns
        if any(token in str(column).casefold() for token in ("time", "timestamp", "second", "ms"))
    ]
    x = numeric[time_candidates[0]] if time_candidates else np.arange(len(numeric))
    columns = [column for column in numeric.columns if column not in time_candidates][:max_columns]
    if not columns:
        return None

    plot_path = output_dir / "sensor_plot.png"
    figure = plt.figure(figsize=(12, 5.5), constrained_layout=True)
    axis = figure.add_subplot(111)
    for column in columns:
        values = pd.to_numeric(numeric[column], errors="coerce")
        axis.plot(x, values, linewidth=0.8, label=str(column))
    axis.set_xlabel(str(time_candidates[0]) if time_candidates else "Row")
    axis.set_ylabel("Sensor value")
    axis.set_title(f"Sensor preview — first {len(numeric):,} rows")
    axis.grid(True, alpha=0.25)
    axis.legend(loc="best", fontsize="small", ncols=2)
    figure.savefig(plot_path, dpi=140)
    plt.close(figure)
    return plot_path


def _write_image_thumbnails(
    image_paths: list[Path],
    output_dir: Path,
    *,
    size: int,
) -> list[Path]:
    thumbnail_dir = output_dir / "images"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, source in enumerate(image_paths):
        try:
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                destination = thumbnail_dir / f"{index:02d}_{source.stem}.jpg"
                image.save(destination, quality=88)
                outputs.append(destination)
        except Exception:
            continue
    return outputs


class PreviewGenerator:
    def __init__(self, config: AppConfig, repository: DatasetRepository | None = None):
        self.config = config
        self.repository = repository or DatasetRepository(config.index_path, config.dataset_root)

    def generate(self, sample_id: str, *, force: bool = False) -> PreviewBundle:
        sample = self.repository.get_sample(sample_id)
        if sample is None:
            raise KeyError(f"Unknown sample_id: {sample_id}")

        output_dir = self.config.previews_dir / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = output_dir / "bundle.json"
        cache_key = sample_cache_key(sample)

        with FileLock(str(output_dir / ".lock"), timeout=120):
            existing = load_bundle(bundle_path)
            if not force and existing and existing.get("cache_key") == cache_key:
                return PreviewBundle.model_validate(existing)

            warnings: list[str] = []
            generated: list[Path] = []
            assets = sample.get("assets", [])

            video_assets = [asset for asset in assets if asset["kind"] == "video"]
            audio_assets = [asset for asset in assets if asset["kind"] == "audio"]
            sensor_assets = [asset for asset in assets if asset["kind"] == "sensor"]
            image_assets = [asset for asset in assets if asset["kind"] == "image"]

            poster: Path | None = None
            contact_sheet: Path | None = None
            waveform: Path | None = None
            spectrogram: Path | None = None
            sensor_plot: Path | None = None

            if video_assets:
                try:
                    poster, contact_sheet = _write_video_previews(
                        Path(video_assets[0]["absolute_path"]),
                        output_dir,
                        count=self.config.preview.video_frames,
                        max_width=self.config.preview.max_width,
                    )
                    generated.extend(path for path in (poster, contact_sheet) if path)
                except Exception as exc:
                    warnings.append(f"Video preview failed: {exc}")

            if audio_assets:
                try:
                    waveform, spectrogram = _write_audio_previews(
                        Path(audio_assets[0]["absolute_path"]),
                        output_dir,
                        max_points=self.config.preview.audio_max_points,
                    )
                    generated.extend(path for path in (waveform, spectrogram) if path)
                except Exception as exc:
                    warnings.append(f"Audio preview failed: {exc}")

            if sensor_assets:
                try:
                    sensor_plot = _write_sensor_preview(
                        Path(sensor_assets[0]["absolute_path"]),
                        output_dir,
                        max_columns=self.config.preview.sensor_max_columns,
                        max_rows=self.config.preview.sensor_max_rows,
                    )
                    if sensor_plot:
                        generated.append(sensor_plot)
                except Exception as exc:
                    warnings.append(f"Sensor preview failed: {exc}")

            thumbnails = _write_image_thumbnails(
                [Path(asset["absolute_path"]) for asset in image_assets],
                output_dir,
                size=self.config.preview.image_thumbnail_size,
            )
            generated.extend(thumbnails)

            bundle = PreviewBundle(
                sample_id=sample_id,
                cache_key=cache_key,
                output_dir=str(output_dir),
                video_poster_url=_uri_or_none(poster),
                video_contact_sheet_url=_uri_or_none(contact_sheet),
                audio_waveform_url=_uri_or_none(waveform),
                audio_spectrogram_url=_uri_or_none(spectrogram),
                sensor_plot_url=_uri_or_none(sensor_plot),
                image_thumbnail_urls=[path.as_uri() for path in thumbnails],
                generated_files=[str(path) for path in generated],
                warnings=warnings,
            )
            bundle_path.write_text(
                json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return bundle
