from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sample_cache_key(sample: dict[str, Any]) -> str:
    assets = [
        {
            "relpath": asset.get("relpath"),
            "size_bytes": asset.get("size_bytes"),
            "mtime_ns": asset.get("mtime_ns"),
        }
        for asset in sample.get("assets", [])
    ]
    payload = json.dumps(assets, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def load_bundle(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
