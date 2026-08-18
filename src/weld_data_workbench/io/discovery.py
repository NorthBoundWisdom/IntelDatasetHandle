from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, SENSOR_EXTENSIONS, VIDEO_EXTENSIONS
from ..domain.models import ManifestMetadata, SampleCandidate
from .manifest import ManifestDocument, candidates_from_manifest, discover_manifest, read_manifest
from .paths import relative_posix, stable_sample_id

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveryResult:
    manifest: ManifestDocument | None
    candidates: list[SampleCandidate]
    notes: list[str] = field(default_factory=list)


def _directory_modality_score(path: Path, files: list[str]) -> int:
    suffixes = {Path(name).suffix.casefold() for name in files}
    score = 0
    if suffixes & VIDEO_EXTENSIONS:
        score += 1
    if suffixes & AUDIO_EXTENSIONS:
        score += 1
    if suffixes & SENSOR_EXTENSIONS:
        score += 1
    try:
        if (path / "images").is_dir() or any(suffix in IMAGE_EXTENSIONS for suffix in suffixes):
            score += 1
    except OSError:
        pass
    return score


def discover_sample_directories(config: AppConfig, manifest_path: Path | None) -> list[Path]:
    root = config.dataset_root
    workspace = config.workspace_root.resolve(strict=False)
    found: list[Path] = []

    for current, dirnames, filenames in os.walk(root, followlinks=config.scan.follow_symlinks):
        path = Path(current)

        # Avoid generated data if a user placed the workspace under the dataset root.
        dirnames[:] = [
            name
            for name in dirnames
            if (config.scan.include_hidden or not name.startswith("."))
            and name.casefold() not in {"__pycache__"}
            and (path / name).resolve(strict=False) != workspace
        ]

        if path.name.casefold() == "images":
            dirnames[:] = []
            continue

        if manifest_path is not None:
            filenames = [name for name in filenames if (path / name) != manifest_path]

        if _directory_modality_score(path, filenames) >= 2:
            found.append(path)
            # Sample directories should not contain nested sample directories except images.
            dirnames[:] = [name for name in dirnames if name.casefold() == "images"]

    return sorted(set(found))


def _merge_candidates(
    root: Path,
    manifest_candidates: list[SampleCandidate],
    filesystem_paths: list[Path],
) -> list[SampleCandidate]:
    by_path: dict[str, SampleCandidate] = {}

    for candidate in manifest_candidates:
        key = candidate.sample_path.resolve(strict=False).as_posix().casefold()
        existing = by_path.get(key)
        if existing is None:
            by_path[key] = candidate
        else:
            for source in candidate.discovered_by:
                if source not in existing.discovered_by:
                    existing.discovered_by.append(source)

    # Unique basename matching is a fallback for manifests whose directory prefix differs.
    manifest_by_basename: dict[str, list[SampleCandidate]] = {}
    for candidate in manifest_candidates:
        manifest_by_basename.setdefault(candidate.sample_path.name.casefold(), []).append(candidate)

    for path in filesystem_paths:
        key = path.resolve(strict=False).as_posix().casefold()
        existing = by_path.get(key)
        if existing is not None:
            if "filesystem" not in existing.discovered_by:
                existing.discovered_by.append("filesystem")
            continue

        matched = manifest_by_basename.get(path.name.casefold(), [])
        metadata = ManifestMetadata()
        discovered_by = ["filesystem"]
        if len(matched) == 1:
            metadata = matched[0].metadata.model_copy(deep=True)
            discovered_by.append("manifest-basename-match")

        relpath = relative_posix(path, root)
        by_path[key] = SampleCandidate(
            sample_id=stable_sample_id(relpath),
            session_id=path.parent.name or "root",
            sample_path=path,
            relpath=relpath,
            metadata=metadata,
            discovered_by=discovered_by,
        )

    candidates = sorted(by_path.values(), key=lambda item: item.relpath.casefold())

    # Keep concise basename IDs when unique. Repeated basenames receive a stable path hash.
    groups: dict[str, list[SampleCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.sample_id, []).append(candidate)
    for base_id, group in groups.items():
        if len(group) <= 1:
            continue
        for candidate in group:
            digest = hashlib.sha1(
                candidate.relpath.encode("utf-8"), usedforsecurity=False
            ).hexdigest()[:10]
            candidate.sample_id = f"{base_id}-{digest}"

    return candidates


def discover_dataset(config: AppConfig) -> DiscoveryResult:
    manifest_path = discover_manifest(
        config.dataset_root,
        preferred_names=config.manifest.preferred_names,
        max_depth=config.manifest.max_search_depth,
    )

    manifest: ManifestDocument | None = None
    manifest_candidates: list[SampleCandidate] = []
    notes: list[str] = []

    if manifest_path is not None:
        manifest = read_manifest(manifest_path)
        manifest_candidates = candidates_from_manifest(manifest, config.dataset_root)
        notes.append(
            f"Manifest: {manifest_path} (score={manifest.score}, rows={len(manifest.dataframe)})"
        )
    else:
        notes.append(
            "No manifest matching the expected schema was found; using filesystem discovery."
        )

    filesystem_paths = discover_sample_directories(config, manifest_path)
    candidates = _merge_candidates(config.dataset_root, manifest_candidates, filesystem_paths)

    logger.info(
        "Discovery found %d candidates (%d manifest-derived, %d filesystem paths)",
        len(candidates),
        len(manifest_candidates),
        len(filesystem_paths),
    )
    return DiscoveryResult(manifest=manifest, candidates=candidates, notes=notes)
