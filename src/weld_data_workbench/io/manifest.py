from __future__ import annotations

import ast
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..constants import EXPECTED_MANIFEST_COLUMNS
from ..domain.categories import normalize_category
from ..domain.models import ManifestMetadata, SampleCandidate
from .paths import relative_posix, stable_sample_id

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ManifestDocument:
    path: Path
    dataframe: pd.DataFrame
    score: int
    matched_columns: set[str]


def normalize_column_name(value: object) -> str:
    text = str(value).strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _iter_limited(root: Path, max_depth: int) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            depth = len(path.relative_to(root).parts) - 1
        except ValueError:
            continue
        if depth <= max_depth:
            yield path


def _candidate_manifest_files(
    root: Path,
    preferred_names: list[str],
    max_depth: int,
) -> list[Path]:
    supported = {".csv", ".tsv", ".txt"}
    preferred_lower = {name.casefold() for name in preferred_names}
    named: list[Path] = []
    fallback: list[Path] = []

    for path in _iter_limited(root, max_depth):
        if path.suffix.casefold() not in supported:
            continue
        name = path.name.casefold()
        if name in preferred_lower or any(
            token in name for token in ("manifest", "annotation", "metadata", "index")
        ):
            named.append(path)
        else:
            fallback.append(path)

    # Prefer root-level and semantically named files. Keep deterministic ordering.
    def key(path: Path) -> tuple[int, str]:
        return len(path.relative_to(root).parts), path.as_posix().casefold()

    return sorted(named, key=key) + sorted(fallback, key=key)


def _read_header(path: Path) -> list[str] | None:
    if path.stat().st_size > 128 * 1024 * 1024:
        return None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            frame = pd.read_csv(path, sep=None, engine="python", nrows=0, encoding=encoding)
            return [normalize_column_name(c) for c in frame.columns]
        except Exception:
            continue
    return None


def score_manifest_columns(columns: Iterable[str]) -> tuple[int, set[str]]:
    normalized = {normalize_column_name(c) for c in columns}
    matched = normalized & EXPECTED_MANIFEST_COLUMNS
    score = len(matched)
    if "CATEGORY" in matched:
        score += 4
    if "SPLIT" in matched:
        score += 2
    if {"DIRECTORY", "SUBDIRS"} & matched:
        score += 3
    return score, matched


def discover_manifest(
    root: Path,
    *,
    preferred_names: list[str],
    max_depth: int,
) -> Path | None:
    best: tuple[int, Path] | None = None
    for path in _candidate_manifest_files(root, preferred_names, max_depth):
        header = _read_header(path)
        if not header:
            continue
        score, matched = score_manifest_columns(header)
        logger.debug("Manifest candidate %s score=%s columns=%s", path, score, sorted(matched))
        # CATEGORY plus path/split/process metadata makes accidental sensor matches unlikely.
        if score < 7 or "CATEGORY" not in matched:
            continue
        if matched == EXPECTED_MANIFEST_COLUMNS:
            return path
        if best is None or score > best[0]:
            best = (score, path)
    return best[1] if best else None


def read_manifest(path: Path) -> ManifestDocument:
    last_error: Exception | None = None
    frame: pd.DataFrame | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            frame = pd.read_csv(path, sep=None, engine="python", encoding=encoding)
            break
        except Exception as exc:
            last_error = exc
    if frame is None:
        raise ValueError(f"Unable to parse manifest {path}: {last_error}")

    original_columns = [str(c) for c in frame.columns]
    normalized_columns = [normalize_column_name(c) for c in original_columns]
    frame.columns = normalized_columns
    score, matched = score_manifest_columns(normalized_columns)
    frame.attrs["original_columns"] = dict(zip(normalized_columns, original_columns, strict=False))
    return ManifestDocument(path=path, dataframe=frame, score=score, matched_columns=matched)


def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null", "na", "n/a"}:
        return None
    return text


def _float_or_none(value: Any) -> float | None:
    text = _clean_scalar(value)
    if text is None:
        return None
    text = text.replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_path_list(value: Any) -> list[str]:
    text = _clean_scalar(value)
    if text is None:
        return []

    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        parsed = None

    if isinstance(parsed, (list, tuple, set)):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        return [parsed.strip()] if parsed.strip() else []

    # Avoid treating a plain numeric sample count as a path.
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return []

    separators = [";", "|", "\n"]
    for separator in separators:
        if separator in text:
            return [part.strip().strip("'\"") for part in text.split(separator) if part.strip()]

    # Commas are common in Python-like lists but can also occur in names. Use only when obvious.
    if "," in text:
        return [part.strip().strip("[]'\"") for part in text.split(",") if part.strip(" []'\"")]

    return [text.strip("[]'\"")]


def _normalized_relpath(text: str | None) -> Path | None:
    if not text:
        return None
    cleaned = text.replace("\\", "/").strip().strip("/")
    if not cleaned:
        return None
    path = Path(cleaned)
    if path.is_absolute() or ".." in path.parts:
        return Path(*[part for part in path.parts if part not in {"..", "/"}])
    return path


def _looks_like_sample_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    direct_suffixes = {p.suffix.casefold() for p in path.iterdir() if p.is_file()}
    has_media = bool(direct_suffixes & {".avi", ".mp4", ".flac", ".wav"})
    has_sensor = bool(direct_suffixes & {".csv", ".tsv"})
    has_images = (path / "images").is_dir()
    return has_media and (has_sensor or has_images)


def _resolve_manifest_sample_path(
    *,
    configured_root: Path,
    manifest_root: Path,
    directory: Path | None,
    subdir: Path,
) -> Path:
    """Resolve both directory-relative and already-prefixed manifest paths.

    Dataset manifests commonly use either ``SUBDIRS=sample`` with a separate
    ``DIRECTORY=session`` value, or ``SUBDIRS=session/sample``. Manifests can
    also live below the configured extraction root. Prefer paths relative to
    the manifest itself, while retaining a configured-root fallback for other
    compatible datasets.
    """
    candidates: list[Path] = []
    includes_directory = directory is not None and (
        subdir == directory or directory in subdir.parents
    )

    for base in (manifest_root, configured_root):
        if directory is not None and not includes_directory:
            candidates.append(base / directory / subdir)
        candidates.append(base / subdir)

    unique_candidates = list(dict.fromkeys(path.resolve(strict=False) for path in candidates))
    for path in unique_candidates:
        if _looks_like_sample_directory(path):
            return path
    for path in unique_candidates:
        if path.exists():
            return path
    return unique_candidates[0]


def _metadata_from_row(row: pd.Series, manifest_path: Path, row_index: int) -> ManifestMetadata:
    raw = {str(key): (None if pd.isna(value) else value) for key, value in row.to_dict().items()}
    category_raw = _clean_scalar(row.get("CATEGORY"))
    split = _clean_scalar(row.get("SPLIT"))
    if split:
        split = split.casefold()
        split = {
            "training": "train",
            "valid": "validation",
            "val": "validation",
            "testing": "test",
        }.get(split, split)

    return ManifestMetadata(
        category_raw=category_raw,
        category=normalize_category(category_raw),
        weld_type=_clean_scalar(row.get("WELD_TYPE")),
        thickness_mm=_float_or_none(row.get("THICKNESS_MM")),
        steel_type=_clean_scalar(row.get("STEEL_TYPE")),
        current_a=_float_or_none(row.get("CURRENT_A")),
        voltage_v=_float_or_none(row.get("VOLTAGE_V")),
        gas_bar=_float_or_none(row.get("GAS_BAR")),
        robot_speed_cpm=_float_or_none(row.get("ROBOT_SPEED_CPM")),
        split=split,
        source_manifest=manifest_path.as_posix(),
        source_row=int(row_index),
        raw=raw,
    )


def candidates_from_manifest(document: ManifestDocument, root: Path) -> list[SampleCandidate]:
    candidates: list[SampleCandidate] = []
    manifest_root = document.path.parent

    for row_index, row in document.dataframe.iterrows():
        metadata = _metadata_from_row(row, document.path, int(row_index))
        try:
            metadata.source_manifest = relative_posix(document.path, root)
        except ValueError:
            metadata.source_manifest = document.path.as_posix()
        directory = _normalized_relpath(_clean_scalar(row.get("DIRECTORY")))
        subdirs = parse_path_list(row.get("SUBDIRS"))
        if not subdirs:
            subdirs = parse_path_list(row.get("SAMPLES"))

        base = manifest_root / directory if directory else manifest_root
        paths: list[Path] = []

        if subdirs:
            for subdir in subdirs:
                rel = _normalized_relpath(subdir)
                if rel is not None:
                    paths.append(
                        _resolve_manifest_sample_path(
                            configured_root=root,
                            manifest_root=manifest_root,
                            directory=directory,
                            subdir=rel,
                        )
                    )
        elif _looks_like_sample_directory(base):
            paths.append(base)
        elif base.is_dir():
            # Some manifests describe one category/session per row and omit an explicit list.
            paths.extend(
                child
                for child in sorted(base.iterdir())
                if child.is_dir() and _looks_like_sample_directory(child)
            )

        # Keep an unresolved path as a structured candidate so validation can report it.
        if not paths and directory is not None:
            paths.append(base)

        for sample_path in paths:
            try:
                relpath = relative_posix(sample_path, root)
            except ValueError:
                continue
            candidates.append(
                SampleCandidate(
                    sample_id=stable_sample_id(relpath),
                    session_id=sample_path.parent.name or "root",
                    sample_path=sample_path,
                    relpath=relpath,
                    metadata=metadata.model_copy(deep=True),
                    discovered_by=["manifest"],
                )
            )

    return candidates
