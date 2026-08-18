from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .real_schema_fixture import _write_audio, _write_images, _write_sensor, _write_video


@dataclass(frozen=True, slots=True)
class BenchmarkFixtureSummary:
    output: Path
    manifest: Path
    samples: int
    sessions: int
    linked_files: int
    copied_files: int


def _link_or_copy(source: Path, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return True
    except OSError:
        shutil.copy2(source, destination)
        return False


def generate_benchmark_fixture(
    output: Path,
    *,
    sessions: int = 8,
    samples_per_session: int = 8,
    seed: int = 20260819,
    force: bool = False,
) -> BenchmarkFixtureSummary:
    """Generate a deterministic many-sample fixture for CI performance smoke tests.

    Media bytes are generated once and then hard-linked where the filesystem permits.
    This keeps CI runtime and disk consumption bounded while still exercising a large
    directory/index cardinality. A copy fallback makes the fixture portable to
    filesystems that do not support hard links.
    """

    if sessions < 1:
        raise ValueError("sessions must be at least 1")
    if samples_per_session < 1:
        raise ValueError("samples_per_session must be at least 1")
    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        if not force:
            raise FileExistsError(f"Output is not empty: {output}. Use force=True to replace it.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    template = output / ".benchmark-template"
    template.mkdir()
    template_video = template / "weld.avi"
    template_audio = template / "weld.flac"
    template_sensor = template / "sensors.csv"
    template_images = template / "images"
    _write_video(template_video, fps=30.0, seed=seed)
    _write_audio(template_audio, sample_rate=16_000, seed=seed)
    _write_sensor(template_sensor, seed=seed)
    _write_images(template_images, seed=seed)

    categories = ("Good", "Porosity", "Undercut", "Spatter")
    splits = ("TRAIN", "VAL", "TEST")
    manifest_rows: list[dict[str, object]] = []
    linked_files = 0
    copied_files = 0

    for session_index in range(sessions):
        category = categories[session_index % len(categories)]
        # Training stays normal-only, matching the dataset's research convention.
        split = "TRAIN" if category == "Good" else splits[1 + (session_index % 2)]
        session_name = f"bench_{session_index:04d}_{category.lower()}_Fe410"
        for sample_index in range(samples_per_session):
            global_index = session_index * samples_per_session + sample_index
            sample_name = f"08-19-26-{global_index:06d}-00"
            sample_dir = output / session_name / sample_name
            sample_dir.mkdir(parents=True, exist_ok=True)

            files = (
                (template_video, sample_dir / "weld.avi"),
                (template_audio, sample_dir / "weld.flac"),
                (template_sensor, sample_dir / "sensors.csv"),
            )
            for source, destination in files:
                if _link_or_copy(source, destination):
                    linked_files += 1
                else:
                    copied_files += 1
            for image_index, source in enumerate(sorted(template_images.glob("*.jpg")), start=1):
                destination = sample_dir / "images" / f"post_weld_{image_index}.jpg"
                if _link_or_copy(source, destination):
                    linked_files += 1
                else:
                    copied_files += 1

            manifest_rows.append(
                {
                    "CATEGORY": category,
                    "WELD_TYPE": "FILLET",
                    "THICKNESS_MM": 7,
                    "STEEL_TYPE": "FE410",
                    "SAMPLES": samples_per_session,
                    "CURRENT_A": 180 + (global_index % 9),
                    "VOLTAGE_V": 23.5 + 0.1 * (global_index % 5),
                    "GAS_BAR": 1.8,
                    "ROBOT_SPEED_CPM": 315 + (global_index % 11),
                    "DIRECTORY": session_name,
                    "SUBDIRS": f"{session_name}/{sample_name}",
                    "SPLIT": split,
                }
            )

    shutil.rmtree(template)
    manifest = output / "manifest.csv"
    pd.DataFrame(manifest_rows).to_csv(manifest, index=False)
    (output / "SYNTHETIC_BENCHMARK_FIXTURE.txt").write_text(
        "Generated benchmark fixture. Contains no Intel dataset bytes.\n",
        encoding="utf-8",
    )
    return BenchmarkFixtureSummary(
        output=output,
        manifest=manifest,
        samples=sessions * samples_per_session,
        sessions=sessions,
        linked_files=linked_files,
        copied_files=copied_files,
    )
