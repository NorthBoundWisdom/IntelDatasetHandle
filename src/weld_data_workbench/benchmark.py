from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows
    resource = None  # type: ignore[assignment]

from . import __version__
from .config import AppConfig
from .features.cache import FeatureJobStore
from .index.repository import DatasetRepository
from .provenance import build_snapshot_payload, snapshot_id

BENCHMARK_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LatencyStats:
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema_version: int
    created_at: str
    tool_version: str
    git_sha: str | None
    snapshot_id: str | None
    platform: dict[str, Any]
    dataset: dict[str, Any]
    repository: dict[str, Any]
    feature_cache: dict[str, int]
    process_peak_rss_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_latency_seconds(values: list[float]) -> LatencyStats:
    milliseconds = [value * 1000.0 for value in values]
    return LatencyStats(
        count=len(milliseconds),
        mean_ms=statistics.fmean(milliseconds) if milliseconds else 0.0,
        p50_ms=_percentile(milliseconds, 0.50),
        p95_ms=_percentile(milliseconds, 0.95),
        max_ms=max(milliseconds, default=0.0),
    )


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    try:
        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # Linux reports KiB; macOS/BSD reports bytes.
    return raw if sys.platform == "darwin" else raw * 1024


def _git_sha() -> str | None:
    explicit = os.environ.get("GITHUB_SHA")
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _timed(callable_) -> tuple[float, Any]:
    start = time.perf_counter()
    result = callable_()
    return time.perf_counter() - start, result


def run_repository_benchmark(
    config: AppConfig,
    *,
    iterations: int = 50,
    page_size: int = 100,
    include_snapshot: bool = True,
) -> BenchmarkReport:
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    repo = DatasetRepository(config.index_path, config.dataset_root)
    stats = repo.stats()
    total = int(stats["total_samples"])
    sample_rows = repo.list_samples(limit=min(max(total, 1), 10_000), sort_by="sample_id")
    sample_ids = [str(row["sample_id"]) for row in sample_rows]

    page_latencies: list[float] = []
    detail_latencies: list[float] = []
    max_offset = max(0, total - min(page_size, max(total, 1)))
    for index in range(iterations):
        offset = 0 if max_offset == 0 else (index * 7919) % (max_offset + 1)
        elapsed, _rows = _timed(
            lambda offset=offset: repo.list_samples(
                limit=page_size,
                offset=offset,
                sort_by="relpath",
            )
        )
        page_latencies.append(elapsed)

        if sample_ids:
            sample_id = sample_ids[(index * 104729) % len(sample_ids)]
            elapsed, detail = _timed(lambda sample_id=sample_id: repo.get_sample(sample_id))
            if detail is None:
                raise RuntimeError(f"Indexed sample disappeared during benchmark: {sample_id}")
            detail_latencies.append(elapsed)

    snapshot_value: str | None = None
    if include_snapshot:
        snapshot_value = snapshot_id(build_snapshot_payload(config))

    feature_cache_path = config.features_dir / "feature_jobs.sqlite3"
    feature_cache: dict[str, int] = {}
    if feature_cache_path.exists():
        feature_cache = FeatureJobStore(feature_cache_path).status_counts()

    repository_metrics = {
        "iterations": iterations,
        "page_size": page_size,
        "list_samples": asdict(summarize_latency_seconds(page_latencies)),
        "get_sample": asdict(summarize_latency_seconds(detail_latencies)),
    }
    dataset_metrics = {
        "samples": total,
        "sessions": int(stats["total_sessions"]),
        "assets": int(stats["total_assets"]),
        "indexed_bytes": int(stats["total_bytes"]),
        "index_size_bytes": config.index_path.stat().st_size,
    }
    platform_metadata = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }

    return BenchmarkReport(
        schema_version=BENCHMARK_SCHEMA_VERSION,
        created_at=datetime.now(UTC).isoformat(),
        tool_version=__version__,
        git_sha=_git_sha(),
        snapshot_id=snapshot_value,
        platform=platform_metadata,
        dataset=dataset_metrics,
        repository=repository_metrics,
        feature_cache=feature_cache,
        process_peak_rss_bytes=_peak_rss_bytes(),
    )


def write_benchmark_report(report: BenchmarkReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
