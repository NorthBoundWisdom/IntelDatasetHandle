from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from . import __version__
from .benchmark import run_repository_benchmark, summarize_latency_seconds
from .config import AppConfig, load_config
from .features.pipeline import FeatureExtractionSummary, FeatureExtractor
from .index.builder import BuildSummary, IndexBuilder
from .index.repository import DatasetRepository
from .previews.generator import (
    PreviewGenerator,
    _write_audio_previews,
    _write_image_thumbnails,
    _write_sensor_preview,
    _write_video_previews,
)

BENCHMARK_SUITE_SCHEMA_VERSION = 1
_MODALITIES = ("video", "audio", "sensor", "image")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteOptions:
    repository_iterations: int = 25
    page_size: int = 100
    scratch_scan: bool = False
    preview_samples: int = 2
    feature_samples: int = 4
    api_requests: int = 32
    api_concurrency: int = 4
    workers: int = 4
    include_snapshot: bool = True
    keep_scratch: bool = False

    def validate(self) -> None:
        integer_bounds = {
            "repository_iterations": (self.repository_iterations, 1),
            "page_size": (self.page_size, 1),
            "preview_samples": (self.preview_samples, 0),
            "feature_samples": (self.feature_samples, 0),
            "api_requests": (self.api_requests, 0),
            "api_concurrency": (self.api_concurrency, 1),
            "workers": (self.workers, 1),
        }
        for name, (value, minimum) in integer_bounds.items():
            if value < minimum:
                raise ValueError(f"{name} must be at least {minimum}")


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteReport:
    schema_version: int
    created_at: str
    tool_version: str
    base: dict[str, Any]
    scratch_scan: dict[str, Any]
    previews: dict[str, Any]
    features: dict[str, Any]
    api: dict[str, Any]
    scratch: dict[str, Any]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clone_config(config: AppConfig, workspace_root: Path) -> AppConfig:
    payload = config.model_dump(mode="python")
    payload["dataset_root"] = config.dataset_root
    payload["workspace_root"] = workspace_root.expanduser().resolve()
    return AppConfig.model_validate(payload)


def _timed(operation: Callable[[], T]) -> tuple[float, T]:
    started = time.perf_counter()
    result = operation()
    return time.perf_counter() - started, result


def _rate(count: int | float, elapsed_s: float) -> float:
    return float(count / elapsed_s) if elapsed_s > 0 else 0.0


def _build_summary(summary: BuildSummary) -> dict[str, Any]:
    return {
        "sample_count": summary.sample_count,
        "asset_count": summary.asset_count,
        "issue_count": summary.issue_count,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "added_sample_count": summary.added_sample_count,
        "reused_sample_count": summary.reused_sample_count,
        "probed_sample_count": summary.probed_sample_count,
        "failed_probe_count": summary.failed_probe_count,
        "removed_sample_count": summary.removed_sample_count,
        "manifest_path": str(summary.manifest_path) if summary.manifest_path else None,
    }


def _feature_summary(summary: FeatureExtractionSummary) -> dict[str, Any]:
    return {
        "samples_requested": summary.samples_requested,
        "samples_completed": summary.samples_completed,
        "samples_failed": summary.samples_failed,
        "feature_columns": summary.feature_columns,
        "jobs_requested": summary.jobs_requested,
        "jobs_reused": summary.jobs_reused,
        "jobs_executed": summary.jobs_executed,
        "jobs_failed": summary.jobs_failed,
        "interrupted_jobs_recovered": summary.interrupted_jobs_recovered,
    }


def _sample_ids(repository: DatasetRepository, requested: int) -> list[str]:
    total = repository.count_samples()
    count = min(max(requested, 0), total)
    if count == 0:
        return []
    offsets = [0] if count == 1 else [round(i * (total - 1) / (count - 1)) for i in range(count)]
    result: list[str] = []
    for offset in offsets:
        rows = repository.list_samples(limit=1, offset=offset, sort_by="sample_id")
        if rows:
            sample_id = str(rows[0]["sample_id"])
            if sample_id not in result:
                result.append(sample_id)
    return result


def _asset_paths(sample: dict[str, Any], kind: str) -> list[Path]:
    assets = [
        asset
        for asset in sample.get("assets", [])
        if asset.get("kind") == kind and asset.get("absolute_path")
    ]
    assets.sort(key=lambda asset: (int(asset.get("ordinal") or 0), str(asset.get("relpath") or "")))
    return [Path(str(asset["absolute_path"])) for asset in assets]


def _reset_directory(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_scratch_scan(config: AppConfig, root: Path, workers: int) -> dict[str, Any]:
    scratch = _clone_config(config, _reset_directory(root / "scan-workspace"))
    scratch.scan.probe_mode = "light"
    scratch.scan.compute_sha256 = False
    full_s, full = _timed(lambda: IndexBuilder(scratch).build(workers=workers))
    noop_s, noop = _timed(lambda: IndexBuilder(scratch).build(workers=workers))
    return {
        "enabled": True,
        "probe_mode": "light",
        "workers": workers,
        "full_scan": {
            "elapsed_s": full_s,
            "samples_per_s": _rate(full.sample_count, full_s),
            "assets_per_s": _rate(full.asset_count, full_s),
            "summary": _build_summary(full),
        },
        "no_op_incremental_scan": {
            "elapsed_s": noop_s,
            "samples_per_s": _rate(noop.sample_count, noop_s),
            "assets_per_s": _rate(noop.asset_count, noop_s),
            "summary": _build_summary(noop),
        },
        "speedup_full_over_no_op": full_s / noop_s if noop_s > 0 else None,
        "no_op_reused_all_samples": (
            noop.sample_count > 0
            and noop.reused_sample_count == noop.sample_count
            and noop.probed_sample_count == 0
        ),
    }


def _preview_one_modality(
    config: AppConfig,
    sample: dict[str, Any],
    modality: str,
    output: Path,
) -> tuple[int, list[str]]:
    output.mkdir(parents=True, exist_ok=True)
    paths = _asset_paths(sample, modality)
    if not paths:
        return 0, [f"missing {modality} asset"]
    if modality == "video":
        poster, sheet = _write_video_previews(
            paths[0], output, count=config.preview.video_frames, max_width=config.preview.max_width
        )
        files = [item for item in (poster, sheet) if item is not None]
    elif modality == "audio":
        waveform, spectrogram = _write_audio_previews(
            paths[0], output, max_points=config.preview.audio_max_points
        )
        files = [item for item in (waveform, spectrogram) if item is not None]
    elif modality == "sensor":
        plot = _write_sensor_preview(
            paths[0],
            output,
            max_columns=config.preview.sensor_max_columns,
            max_rows=config.preview.sensor_max_rows,
        )
        files = [plot] if plot is not None else []
    elif modality == "image":
        files = _write_image_thumbnails(paths, output, size=config.preview.image_thumbnail_size)
    else:
        raise ValueError(f"Unsupported preview modality: {modality}")
    return len(files), [] if files else [f"{modality} preview produced no files"]


def _run_preview_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    root: Path,
    sample_limit: int,
) -> dict[str, Any]:
    selected = _sample_ids(repository, sample_limit)
    if not selected:
        return {
            "enabled": False,
            "reason": "no samples selected",
            "requested_samples": sample_limit,
        }

    preview_config = _clone_config(config, _reset_directory(root / "preview-workspace"))
    generator = PreviewGenerator(preview_config, repository)
    latencies: dict[str, list[float]] = {modality: [] for modality in _MODALITIES}
    files_written: dict[str, int] = {modality: 0 for modality in _MODALITIES}
    warnings: dict[str, list[str]] = {modality: [] for modality in _MODALITIES}
    cold: list[float] = []
    warm: list[float] = []
    cold_files = 0
    warm_files = 0

    for sample_id in selected:
        sample = repository.get_sample(sample_id)
        if sample is None:
            for modality in _MODALITIES:
                warnings[modality].append(f"{sample_id}: sample disappeared")
            continue
        for modality in _MODALITIES:
            target = _reset_directory(root / "preview-modalities" / sample_id / modality)
            started = time.perf_counter()
            try:
                count, messages = _preview_one_modality(preview_config, sample, modality, target)
            except Exception as exc:
                warnings[modality].append(f"{sample_id}: {type(exc).__name__}: {exc}")
                continue
            latencies[modality].append(time.perf_counter() - started)
            files_written[modality] += count
            warnings[modality].extend(f"{sample_id}: {message}" for message in messages)

        started = time.perf_counter()
        bundle = generator.generate(sample_id, force=True)
        cold.append(time.perf_counter() - started)
        cold_files += len(bundle.generated_files)
        started = time.perf_counter()
        bundle = generator.generate(sample_id, force=False)
        warm.append(time.perf_counter() - started)
        warm_files += len(bundle.generated_files)

    per_modality: dict[str, Any] = {}
    for modality in _MODALITIES:
        stats = summarize_latency_seconds(latencies[modality])
        per_modality[modality] = {
            "latency": asdict(stats),
            "samples_completed": stats.count,
            "files_written": files_written[modality],
            "warnings": warnings[modality],
        }
    cold_stats = summarize_latency_seconds(cold)
    warm_stats = summarize_latency_seconds(warm)
    return {
        "enabled": True,
        "requested_samples": sample_limit,
        "selected_samples": selected,
        "modality_generation": per_modality,
        "bundle_generation": {
            "cold": {"latency": asdict(cold_stats), "generated_files": cold_files},
            "warm_cache": {"latency": asdict(warm_stats), "generated_files": warm_files},
            "warm_speedup_mean": (
                cold_stats.mean_ms / warm_stats.mean_ms if warm_stats.mean_ms > 0 else None
            ),
        },
    }


def _run_feature_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    root: Path,
    sample_limit: int,
    workers: int,
) -> dict[str, Any]:
    if sample_limit <= 0 or repository.count_samples() <= 0:
        return {
            "enabled": False,
            "reason": "feature sample limit is zero or dataset is empty",
            "requested_samples": sample_limit,
        }
    feature_config = _clone_config(config, _reset_directory(root / "feature-workspace"))
    extractor = FeatureExtractor(feature_config, repository)
    results: dict[str, Any] = {}
    for modality in _MODALITIES:
        output = feature_config.features_dir / f"benchmark-{modality}.csv"
        started = time.perf_counter()
        cold = extractor.extract(
            output,
            modalities=(modality,),
            limit=sample_limit,
            workers=workers,
            force=True,
        )
        cold_s = time.perf_counter() - started
        started = time.perf_counter()
        warm = extractor.extract(
            output,
            modalities=(modality,),
            limit=sample_limit,
            workers=workers,
            force=False,
        )
        warm_s = time.perf_counter() - started
        results[modality] = {
            "cold": {
                "elapsed_s": cold_s,
                "samples_per_s": _rate(cold.samples_completed, cold_s),
                "jobs_per_s": _rate(cold.jobs_executed, cold_s),
                "summary": _feature_summary(cold),
            },
            "warm_cache": {
                "elapsed_s": warm_s,
                "samples_per_s": _rate(warm.samples_completed, warm_s),
                "jobs_per_s": _rate(warm.jobs_reused, warm_s),
                "summary": _feature_summary(warm),
            },
            "warm_speedup": cold_s / warm_s if warm_s > 0 else None,
        }
    return {
        "enabled": True,
        "requested_samples": sample_limit,
        "workers": workers,
        "modalities": results,
    }


async def _run_api_async(
    workspace: Path,
    sample_ids: list[str],
    requests: int,
    concurrency: int,
    page_size: int,
) -> dict[str, Any]:
    try:
        import httpx

        from .api.app import create_app
    except ImportError as exc:
        return {"enabled": False, "reason": f"API benchmark dependency unavailable: {exc}"}

    app = create_app(workspace)
    transport = httpx.ASGITransport(app=app)
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: dict[str, int] = {}

    async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.local") as client:

        async def request(index: int) -> None:
            path = (
                f"/api/samples/{sample_ids[index % len(sample_ids)]}"
                if sample_ids and index % 2
                else f"/api/samples?limit={page_size}&offset=0"
            )
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(path)
                latencies.append(time.perf_counter() - started)
            status = str(response.status_code)
            statuses[status] = statuses.get(status, 0) + 1

        started = time.perf_counter()
        await asyncio.gather(*(request(index) for index in range(requests)))
        wall_s = time.perf_counter() - started

    successful = statuses.get("200", 0)
    return {
        "enabled": True,
        "transport": "httpx.ASGITransport",
        "requests": requests,
        "concurrency": concurrency,
        "wall_s": wall_s,
        "requests_per_s": _rate(requests, wall_s),
        "successful_requests_per_s": _rate(successful, wall_s),
        "latency": asdict(summarize_latency_seconds(latencies)),
        "status_counts": statuses,
    }


def _run_api_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    requests: int,
    concurrency: int,
    page_size: int,
) -> dict[str, Any]:
    if requests <= 0:
        return {"enabled": False, "reason": "api_requests is zero", "requests": requests}
    sample_ids = _sample_ids(repository, min(concurrency, 16))
    try:
        return asyncio.run(
            _run_api_async(config.config_path, sample_ids, requests, concurrency, page_size)
        )
    except RuntimeError as exc:
        return {"enabled": False, "reason": f"API benchmark event-loop failure: {exc}"}


def _scratch_root(parent: Path | None) -> tuple[Path, bool]:
    if parent is None:
        return Path(tempfile.mkdtemp(prefix="weld-benchmark-suite-")), True
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{time.time_ns()}"
    root.mkdir()
    return root, False


def _optional_stage(
    name: str, operation: Callable[[], dict[str, Any]], warnings: list[str]
) -> dict[str, Any]:
    try:
        return operation()
    except Exception as exc:
        message = f"{name} benchmark failed: {type(exc).__name__}: {exc}"
        warnings.append(message)
        return {"enabled": False, "reason": message}


def run_benchmark_suite(
    config: AppConfig,
    *,
    options: BenchmarkSuiteOptions | None = None,
    scratch_root: Path | None = None,
) -> BenchmarkSuiteReport:
    selected = options or BenchmarkSuiteOptions()
    selected.validate()
    repository = DatasetRepository(config.index_path, config.dataset_root)
    root, auto_owned = _scratch_root(scratch_root)
    warnings: list[str] = []
    try:
        base = run_repository_benchmark(
            config,
            iterations=selected.repository_iterations,
            page_size=selected.page_size,
            include_snapshot=selected.include_snapshot,
        ).to_dict()
        scratch_scan = (
            _optional_stage(
                "scratch scan", lambda: _run_scratch_scan(config, root, selected.workers), warnings
            )
            if selected.scratch_scan
            else {"enabled": False, "reason": "scratch_scan option disabled"}
        )
        previews = _optional_stage(
            "preview",
            lambda: _run_preview_benchmark(config, repository, root, selected.preview_samples),
            warnings,
        )
        features = _optional_stage(
            "feature",
            lambda: _run_feature_benchmark(
                config, repository, root, selected.feature_samples, selected.workers
            ),
            warnings,
        )
        api = _optional_stage(
            "API",
            lambda: _run_api_benchmark(
                config,
                repository,
                selected.api_requests,
                selected.api_concurrency,
                selected.page_size,
            ),
            warnings,
        )
        return BenchmarkSuiteReport(
            schema_version=BENCHMARK_SUITE_SCHEMA_VERSION,
            created_at=datetime.now(UTC).isoformat(),
            tool_version=__version__,
            base=base,
            scratch_scan=scratch_scan,
            previews=previews,
            features=features,
            api=api,
            scratch={
                "path": str(root),
                "retained": selected.keep_scratch,
                "auto_owned": auto_owned,
            },
            warnings=warnings,
        )
    finally:
        if not selected.keep_scratch:
            shutil.rmtree(root, ignore_errors=True)


def write_benchmark_suite_report(report: BenchmarkSuiteReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the comprehensive welding benchmark suite.")
    parser.add_argument("--workspace", "-w", type=Path, required=True)
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--repository-iterations", type=int, default=25)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--scratch-scan", action="store_true")
    parser.add_argument("--preview-samples", type=int, default=2)
    parser.add_argument("--feature-samples", type=int, default=4)
    parser.add_argument("--api-requests", type=int, default=32)
    parser.add_argument("--api-concurrency", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument("--keep-scratch", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(args.workspace)
    report = run_benchmark_suite(
        config,
        options=BenchmarkSuiteOptions(
            repository_iterations=args.repository_iterations,
            page_size=args.page_size,
            scratch_scan=args.scratch_scan,
            preview_samples=args.preview_samples,
            feature_samples=args.feature_samples,
            api_requests=args.api_requests,
            api_concurrency=args.api_concurrency,
            workers=args.workers,
            include_snapshot=not args.no_snapshot,
            keep_scratch=args.keep_scratch,
        ),
        scratch_root=args.scratch_root,
    )
    destination = write_benchmark_suite_report(
        report, args.output or (config.reports_dir / "benchmark-suite.json")
    )
    print(
        json.dumps(
            {
                "output": str(destination),
                "schema_version": report.schema_version,
                "snapshot_id": report.base.get("snapshot_id"),
                "scratch_scan_enabled": bool(report.scratch_scan.get("enabled")),
                "preview_enabled": bool(report.previews.get("enabled")),
                "features_enabled": bool(report.features.get("enabled")),
                "api_enabled": bool(report.api.get("enabled")),
                "warnings": report.warnings,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
