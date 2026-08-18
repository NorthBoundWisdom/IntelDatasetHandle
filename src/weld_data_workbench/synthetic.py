from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import soundfile as sf
from PIL import Image, ImageDraw

from .domain.categories import CANONICAL_CATEGORIES


@dataclass(slots=True)
class SyntheticSummary:
    output: Path
    samples: int
    sessions: int
    manifest: Path


def _category_color(category: str) -> tuple[int, int, int]:
    seed = sum(ord(char) for char in category)
    return (60 + seed % 150, 60 + (seed * 3) % 150, 60 + (seed * 7) % 150)


def _write_video(path: Path, *, category: str, seed: int, frames: int = 24) -> None:
    width, height, fps = 192, 112, 24.0
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create the synthetic AVI fixture")

    rng = np.random.default_rng(seed)
    base = _category_color(category)
    for index in range(frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (18, 18, 22)
        x = 15 + int((width - 30) * index / max(frames - 1, 1))
        y = height // 2 + int(12 * math.sin(index / 3.0))
        radius = 7 if category == "Good" else 9 + (seed % 4)
        cv2.circle(frame, (x, y), radius, base[::-1], thickness=-1)
        cv2.line(frame, (10, height - 25), (width - 10, height - 25), (170, 170, 170), 2)
        if category != "Good":
            for _ in range(5):
                px = int(np.clip(x + rng.normal(0, 18), 0, width - 1))
                py = int(np.clip(y + rng.normal(0, 18), 0, height - 1))
                cv2.circle(frame, (px, py), 2, (235, 235, 235), thickness=-1)
        cv2.putText(
            frame,
            category.replace("_", " ")[:24],
            (8, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )
        writer.write(frame)
    writer.release()


def _write_audio(path: Path, *, category: str, seed: int) -> None:
    sample_rate = 16_000
    duration = 1.8
    time = np.arange(int(sample_rate * duration), dtype=np.float32) / sample_rate
    rng = np.random.default_rng(seed)
    base_frequency = 650.0 + (seed % 5) * 70.0
    audio = 0.18 * np.sin(2 * np.pi * base_frequency * time)
    audio += 0.04 * rng.standard_normal(time.shape).astype(np.float32)
    if category != "Good":
        burst = np.zeros_like(audio)
        start = int(0.65 * sample_rate)
        end = min(len(audio), start + int(0.18 * sample_rate))
        burst[start:end] = 0.25 * np.sin(2 * np.pi * (2_300 + seed % 700) * time[: end - start])
        audio += burst
    sf.write(path, np.clip(audio, -1.0, 1.0), sample_rate, format="FLAC")


def _write_sensor(path: Path, *, category: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    rows = 240
    t = np.linspace(0, 1.8, rows)
    current = 180 + 4 * np.sin(2 * np.pi * 3 * t) + rng.normal(0, 1.1, rows)
    voltage = 24 + 0.6 * np.sin(2 * np.pi * 2 * t + 0.4) + rng.normal(0, 0.15, rows)
    gas = np.full(rows, 1.8) + rng.normal(0, 0.02, rows)
    wire_feed = np.full(rows, 320.0) + rng.normal(0, 1.2, rows)
    if category != "Good":
        anomaly = slice(rows // 3, rows // 3 + rows // 7)
        current[anomaly] += 14 + seed % 9
        voltage[anomaly] -= 1.8
    frame = pd.DataFrame(
        {
            "timestamp_s": t,
            "current_a": current,
            "voltage_v": voltage,
            "gas_bar": gas,
            "wire_feed_cpm": wire_feed,
            "arc_state": (current > 100).astype(int),
        }
    )
    frame.to_csv(path, index=False)


def _write_images(directory: Path, *, category: str, seed: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    base = _category_color(category)
    for index in range(5):
        image = Image.new("RGB", (320, 220), (30, 32, 35))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (25, 80, 295, 145), radius=16, fill=base, outline=(210, 210, 210), width=2
        )
        draw.line((35, 112, 285, 112), fill=(235, 235, 235), width=3)
        if category != "Good":
            for _ in range(8):
                x = int(rng.integers(55, 270))
                y = int(rng.integers(92, 134))
                radius = int(rng.integers(2, 6))
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(20, 20, 20))
        draw.text(
            (14, 14), f"{category.replace('_', ' ')} — view {index + 1}", fill=(235, 235, 235)
        )
        image.save(directory / f"post_weld_{index + 1}.jpg", quality=88)


def generate_synthetic_dataset(
    output: Path,
    *,
    profile: str = "tiny",
    force: bool = False,
    seed: int = 20260818,
) -> SyntheticSummary:
    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        if not force:
            raise FileExistsError(f"Output is not empty: {output}. Use force=True to replace it.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    defects = list(CANONICAL_CATEGORIES[1:])
    if profile == "tiny":
        defects = defects[:3]
        plan = [
            ("train", "Good", 4),
            ("validation", "Good", 2),
            ("test", "Good", 2),
            *[("validation", category, 1) for category in defects],
            *[("test", category, 1) for category in defects],
        ]
    elif profile in {"taxonomy", "full-taxonomy"}:
        plan = [
            ("train", "Good", 12),
            ("validation", "Good", 6),
            ("test", "Good", 6),
            *[("validation", category, 1) for category in defects],
            *[("test", category, 1) for category in defects],
        ]
    else:
        raise ValueError("profile must be 'tiny' or 'taxonomy'")

    manifest_rows: list[dict[str, object]] = []
    sample_index = 0
    sessions: set[str] = set()
    for split, category, count in plan:
        for local_index in range(count):
            sample_index += 1
            session_id = f"session_{split}_{local_index // 4:02d}_{category.casefold()[:8]}"
            sample_id = f"{category.casefold().replace('_', '-')}_{split}_{local_index:03d}"
            sessions.add(session_id)
            sample_dir = output / session_id / sample_id
            sample_dir.mkdir(parents=True, exist_ok=True)
            item_seed = seed + sample_index * 17

            _write_video(sample_dir / "weld.avi", category=category, seed=item_seed)
            _write_audio(sample_dir / "weld.flac", category=category, seed=item_seed)
            _write_sensor(sample_dir / "sensors.csv", category=category, seed=item_seed)
            _write_images(sample_dir / "images", category=category, seed=item_seed)

            manifest_rows.append(
                {
                    "CATEGORY": category,
                    "WELD_TYPE": "fillet" if sample_index % 2 else "non-fillet",
                    "THICKNESS_MM": 7 if sample_index % 3 else 3,
                    "STEEL_TYPE": "FE410" if sample_index % 4 else "BSK46",
                    "SAMPLES": 1,
                    "CURRENT_A": 180 + sample_index % 8,
                    "VOLTAGE_V": 24.0 + (sample_index % 5) * 0.2,
                    "GAS_BAR": 1.8,
                    "ROBOT_SPEED_CPM": 320 + sample_index % 10,
                    "DIRECTORY": session_id,
                    "SUBDIRS": json.dumps([sample_id]),
                    "SPLIT": split,
                }
            )

    manifest = output / "manifest.csv"
    pd.DataFrame(manifest_rows).to_csv(manifest, index=False)
    (output / "SYNTHETIC_DATASET.txt").write_text(
        "Generated by WeldDataWorkbench. Contains no Intel data.\n",
        encoding="utf-8",
    )
    return SyntheticSummary(
        output=output,
        samples=len(manifest_rows),
        sessions=len(sessions),
        manifest=manifest,
    )
