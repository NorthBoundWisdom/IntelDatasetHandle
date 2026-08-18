from __future__ import annotations

import hashlib
import re
from pathlib import Path


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def safe_slug(value: str, *, fallback: str = "sample", max_length: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    slug = slug[:max_length]
    return slug or fallback


def stable_sample_id(relpath: str) -> str:
    """Return a human-readable provisional ID.

    Dataset discovery adds a deterministic path hash only when the same basename occurs
    more than once, keeping common sample IDs concise without sacrificing uniqueness.
    """
    return safe_slug(Path(relpath).name)


def stable_asset_id(sample_id: str, kind: str, relpath: str, ordinal: int) -> str:
    payload = f"{sample_id}\0{kind}\0{ordinal}\0{relpath}".encode()
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def safe_join(root: Path, relpath: str) -> Path:
    candidate = (root / relpath).resolve(strict=False)
    if not is_relative_to(candidate, root):
        raise ValueError(f"Path escapes root: {relpath}")
    return candidate


def path_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return 10_000
