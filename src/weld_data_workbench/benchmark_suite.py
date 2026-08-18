from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
        if self.repository_iterations < 1:
            raise ValueError("repository_iterations must be at least 1")
        if self.page_size < 1:
            raise ValueError("page_size must be at least 1")
        if self.preview_samples < 0:
            raise ValueError("preview_samples must not be negative")
        if self.feature_samples < 0:
            raise ValueError("feature_samples must not be negative")
        if self.api_requests < 0:
            raise ValueError("api_requests must not be negative")
        if self.api_concurrency < 1:
            raise ValueError("api_concurrency must be at least 1")
        if self.workers < 1:
            raise ValueError("workers must be at least 1")


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


def _timed(callable_) -> tuple[float, Any]:
    started = time.perf_counter()
    result = callable_()
    return time.perf_counter() - started, result


def _rate(count: int | float, elapsed_s: float) -> float:
    return float(count / elapsed_s) if elapsed_s > 0 else 0.0


def _summary_payload(summary: BuildSummary) -> dict[str, Any]:
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


def _feature_summary_payload(summary: FeatureExtractionSummary) -> dict[str, Any]:
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
    if requested <= 0:
        return []
    total = repository.count_samples()
    if total <= 0:
        return []
    count = min(requested, total)
    if count == 1:
        offsets = [0]
    else:
        offsets = [
            round(index * (total - 1) / (count - 1))
            for index in range(count)
        ]
    selected: list[str] = []
    seen: set[str] = set()
    for offset in offsets:
        rows = repository.list_samples(
            limit=1,
            offset=offset,
            sort_by="sample_id",
        )
        if not rows:
            continue
        sample_id = str(rows[0]["sample_id"])
        if sample_id not in seen:
            seen.add(sample_id)
            selected.append(sample_id)
    return selected


def _asset_paths(sample: dict[str, Any], kind: str) -> list[Path]:
    assets = [
        asset
        for asset in sample.get("assets", [])
        if asset.get("kind") == kind and asset.get("absolute_path")
    ]
    assets.sort(
        key=lambda asset: (
            int(asset.get("ordinal") or 0),
            str(asset.get("relpath") or ""),
        )
    )
    return [Path(str(asset["absolute_path"])) for asset in assets]


def _prepare_empty_directory(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_preview_modality(
    config: AppConfig,
    sample: dict[str, Any],
    modality: str,
    output_dir: Path,
) -> tuple[int, list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    paths = _asset_paths(sample, modality)

    if modality == "video":
        if not paths:
            return 0, ["missing video asset"]
        poster, contact_sheet = _write_video_previews(
            paths[0],
            output_dir,
            count=config.preview.video_frames,
            max_width=config.preview.max_width,
        )
        outputs = [path for path in (poster, contact_sheet) if path is not None]
        if not outputs:
            warnings.append("video preview produced no files")
        return len(outputs), warnings

    if modality == "audio":
        if not paths:
            return 0, ["missing audio asset"]
        waveform, spectrogram = _write_audio_previews(
            paths[0],
            output_dir,
            max_points=config.preview.audio_max_points,
        )
        outputs = [path for path in (waveform, spectrogram) if path is not None]
        if not outputs:
            warnings.append("audio preview produced no files")
        return len(outputs), warnings

    if modality == "sensor":
        if not paths:
            return 0, ["missing sensor asset"]
        plot = _write_sensor_preview(
            paths[0],
            output_dir,
            max_columns=config.preview.sensor_max_columns,
            max_rows=config.preview.sensor_max_rows,
        )
        if plot is None:
            warnings.append("sensor preview produced no file")
            return 0, warnings
        return 1, warnings

    if modality == "image":
        if not paths:
            return 0, ["missing image assets"]
        outputs = _write_image_thumbnails(
            paths,
            output_dir,
            size=config.preview.image_thumbnail_size,
        )
        if not outputs:
            warnings.append("image preview produced no files")
        return len(outputs), warnings

    raise ValueError(f"Unsupported preview modality: {modality}")


def _run_scratch_scan(
    config: AppConfig,
    scratch_root: Path,
    *,
    workers: int,
) -> dict[str, Any]:
    workspace = scratch_root / "scan-workspace"
    _prepare_empty_directory(workspace)
    scratch_config = _clone_config(config, workspace)
    scratch_config.scan.probe_mode = "light"
    scratch_config.scan.compute_sha256 = False

    first_elapsed, first = _timed(
        lambda: IndexBuilder(scratch_config).build(workers=workers)
    )
    second_elapsed, second = _timed(
        lambda: IndexBuilder(scratch_config).build(workers=workers)
    )

    return {
        "enabled": True,
        "probe_mode": "light",
        "workers": workers,
        "full_scan": {
            "elapsed_s": first_elapsed,
            "samples_per_s": _rate(first.sample_count, first_elapsed),
            "assets_per_s": _rate(first.asset_count, first_elapsed),
            "summary": _summary_payload(first),
        },
        "no_op_incremental_scan": {
            "elapsed_s": second_elapsed,
            "samples_per_s": _rate(second.sample_count, second_elapsed),
            "assets_per_s": _rate(second.asset_count, second_elapsed),
            "summary": _summary_payload(second),
        },
        "speedup_full_over_no_op": (
            first_elapsed / second_elapsed if second_elapsed > 0 else None
        ),
        "no_op_reused_all_samples": (
            second.sample_count > 0
            and second.reused_sample_count == second.sample_count
            and second.probed_sample_count == 0
        ),
    }


def _run_preview_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    scratch_root: Path,
    *,
    sample_limit: int,
) -> dict[str, Any]:
    sample_ids = _sample_ids(repository, sample_limit)
    if not sample_ids:
        return {
            "enabled": False,
            "reason": "no samples selected",
            "requested_samples": sample_limit,
        }

    workspace = scratch_root / "preview-workspace"
    _prepare_empty_directory(workspace)
    preview_config = _clone_config(config, workspace)
    generator = PreviewGenerator(preview_config, repository)

    modality_latencies: dict[str, list[float]] = {
        modality: [] for modality in _MODALITIES
    }
    modality_files: dict[str, int] = {modality: 0 for modality in _MODALITIES}
    modality_warnings: dict[str, list[str]] = {
        modality: [] for modality in _MODALITIES
    }
    cold_bundle_latencies: list[float] = []
    warm_bundle_latencies: list[float] = []
    cold_generated_files = 0
    warm_generated_files = 0

    for sample_id in sample_ids:
        sample = repository.get_sample(sample_id)
        if sample is None:
            for modality in _MODALITIES:
                modality_warnings[modality].append(
                    f"{sample_id}: sample disappeared during benchmark"
                )
            continue

        for modality in _MODALITIES:
            target = (
                scratch_root
                / "preview-modalities"
                / sample_id
                / modality
            )
            _prepare_empty_directory(target)
            try:
                elapsed, result = _timed(
                    lambda modality=modality, target=target, sample=sample: (
                        _run_preview_modality(
                            preview_config,
                            sample,
                            modality,
                            target,
                        )
                    )
                )
            except Exception as exc:
                modality_warnings[modality].append(
                    f"{sample_id}: {type(exc).__name__}: {exc}"
                )
                continue
            files_written, warnings = result
            modality_latencies[modality].append(elapsed)
            modality_files[modality] += files_written
            modality_warnings[modality].extend(
                f"{sample_id}: {warning}" for warning in warnings
            )

        cold_elapsed, cold_bundle = _timed(
            lambda sample_id=sample_id: generator.generate(
                sample_id,
                force=True,
            )
        )
        cold_bundle_latencies.append(cold_elapsed)
        cold_generated_files += len(cold_bundle.generated_files)

        warm_elapsed, warm_bundle = _timed(
            lambda sample_id=sample_id: generator.generate(
                sample_id,
                force=False,
            )
        )
        warm_bundle_latencies.append(warm_elapsed)
        warm_generated_files += len(warm_bundle.generated_files)

    modality_payload: dict[str, Any] = {}
    for modality in _MODALITIES:
        latency = summarize_latency_seconds(modality_latencies[modality])
        modality_payload[modality] = {
            "latency": asdict(latency),
            "samples_completed": latency.count,
            "files_written": modality_files[modality],
            "warnings": modality_warnings[modality],
        }

    cold = summarize_latency_seconds(cold_bundle_latencies)
    warm = summarize_latency_seconds(warm_bundle_latencies)
    return {
        "enabled": True,
        "requested_samples": sample_limit,
        "selected_samples": sample_ids,
        "modality_generation": modality_payload,
        "bundle_generation": {
            "cold": {
                "latency": asdict(cold),
                "generated_files": cold_generated_files,
            },
            "warm_cache": {
                "latency": asdict(warm),
                "generated_files": warm_generated_files,
            },
            "warm_speedup_mean": (
                cold.mean_ms / warm.mean_ms if warm.mean_ms > 0 else None
            ),
        },
    }


def _run_feature_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    scratch_root: Path,
    *,
    sample_limit: int,
    workers: int,
) -> dict[str, Any]:
    if sample_limit <= 0 or repository.count_samples() <= 0:
        return {
            "enabled": False,
            "reason": "feature sample limit is zero or dataset is empty",
            "requested_samples": sample_limit,
        }

    workspace = scratch_root / "feature-workspace"
    _prepare_empty_directory(workspace)
    feature_config = _clone_config(config, workspace)
    extractor = FeatureExtractor(feature_config, repository)
    stages: dict[str, Any] = {}

    for modality in _MODALITIES:
        output = workspace / "outputs" / f"{modality}.csv"
        cold_elapsed, cold = _timed(
            lambda modality=modality, output=output: extractor.extract(
                output,
                modalities=(modality,),
                limit=sample_limit,
                workers=workers,
                force=True,
            )
        )
        warm_elapsed, warm = _timed(
            lambda modality=modality, output=output: extractor.extract(
                output,
                modalities=(modality,),
                limit=sample_limit,
                workers=workers,
                force=False,
            )
        )
        stages[modality] = {
            "cold": {
                "elapsed_s": cold_elapsed,
                "samples_per_s": _rate(cold.samples_completed, cold_elapsed),
                "jobs_per_s": _rate(cold.jobs_executed, cold_elapsed),
                "summary": _feature_summary_payload(cold),
            },
            "warm_cache": {
                "elapsed_s": warm_elapsed,
                "samples_per_s": _rate(warm.samples_completed, warm_elapsed),
                "jobs_per_s": _rate(warm.jobs_reused, warm_elapsed),
                "summary": _feature_summary_payload(warm),
            },
            "warm_speedup": (
                cold_elapsed / warm_elapsed if warm_elapsed > 0 else None
            ),
        }

    return {
        "enabled": True,
        "requested_samples": sample_limit,
        "workers": workers,
        "modalities": stages,
    }


async def _api_requests_async(
    workspace: Path,
    *,
    requests: int,
    concurrency: int,
    page_size: int,
    sample_ids: list[str],
) -> dict[str, Any]:
    try:
        import httpx
        from .api.app import create_app
    except ImportError as exc:
        return {
            "enabled": False,
            "reason": f"API benchmark dependency unavailable: {exc}",
        }

    app = create_app(workspace)
    transport = httpx.ASGITransport(app=app)
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_counts: dict[str, int] = {}

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://benchmark.local",
        timeout=30.0,
    ) as client:

        async def one(index: int) -> None:
            if sample_ids and index % 2:
                sample_id = sample_ids[index % len(sample_ids)]
                path = f"/api/samples/{quote(sample_id, safe='')}"
            else:
                offset = 0
                path = f"/api/samples?limit={page_size}&offset={offset}"
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(path)
                elapsed = time.perf_counter() - started
            latencies.append(elapsed)
            key = str(response.status_code)
            status_counts[key] = status_counts.get(key, 0) + 1

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(requests)))
        wall_s = time.perf_counter() - started

    latency = summarize_latency_seconds(latencies)
    success = status_counts.get("200", 0)
    return {
        "enabled": True,
        "transport": "httpx.ASGITransport",
        "requests": requests,
        "concurrency": concurrency,
        "wall_s": wall_s,
        "requests_per_s": _rate(requests, wall_s),
        "successful_requests_per_s": _rate(success, wall_s),
        "latency": asdict(latency),
        "status_counts": status_counts,
    }


def _run_api_benchmark(
    config: AppConfig,
    repository: DatasetRepository,
    *,
    requests: int,
    concurrency: int,
    page_size: int,
) -> dict[str, Any]:
    if requests <= 0:
        return {
            "enabled": False,
            "reason": "api_requests is zero",
            "requests": requests,
        }
    sample_ids = _sample_ids(repository, min(max(concurrency, 1), 16))
    try:
        return asyncio.run(
            _api_requests_async(
                config.config_path,
                requests=requests,
                concurrency=concurrency,
                page_size=page_size,
                sample_ids=sample_ids,
            )
        )
    except RuntimeError as exc:
        return {
            "enabled": False,
            "reason": f"API benchmark could not create an event loop: {exc}",
        }


def _create_scratch_root(
    scratch_root: Path | None,
) -> tuple[Path, bool]:
    if scratch_root is None:
        return Path(tempfile.mkdtemp(prefix="weld-benchmark-suite-")), True

    parent = scratch_root.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    run_root = parent / (
        f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{time.time_ns()}"
    )
    run_root.mkdir(parents=False, exist_ok=False)
    return run_root, False


def run_benchmark_suite(
    config: AppConfig,
    *,
    options: BenchmarkSuiteOptions | None = None,
    scratch_root: Path | None = None,
) -> BenchmarkSuiteReport:
    selected = options or BenchmarkSuiteOptions()
    selected.validate()

    repository = DatasetRepository(config.index_path, config.dataset_root)
    root, auto_owned = _create_scratch_root(scratch_root)
    warnings: list[str] = []

    try:
        base = run_repository_benchmark(
            config,
            iterations=selected.repository_iterations,
            page_size=selected.page_size,
            include_snapshot=selected.include_snapshot,
        ).to_dict()

        if selected.scratch_scan:
            try:
                scratch_scan = _run_scratch_scan(
                    config,
                    root,
                    workers=selected.workers,
                )
            except Exception as exc:
                scratch_scan = {
                    "enabled": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                warnings.append(
                    f"scratch scan benchmark failed: {type(exc).__name__}: {exc}"
                )
        else:
            scratch_scan = {
                "enabled": False,
                "reason": "scratch_scan option disabled",
            }

        try:
            previews = _run_preview_benchmark(
                config,
                repository,
                root,
                sample_limit=selected.preview_samples,
            )
        except Exception as exc:
            previews = {
                "enabled": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            warnings.append(
                f"preview benchmark failed: {type(exc).__name__}: {exc}"
            )

        try:
            features = _run_feature_benchmark(
                config,
                repository,
                root,
                sample_limit=selected.feature_samples,
                workers=selected.workers,
            )
        except Exception as exc:
            features = {
                "enabled": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            warnings.append(
                f"feature benchmark failed: {type(exc).__name__}: {exc}"
            )

        try:
            api = _run_api_benchmark(
                config,
                repository,
                requests=selected.api_requests,
                concurrency=selected.api_concurrency,
                page_size=selected.page_size,
            )
        except Exception as exc:
            api = {
                "enabled": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            warnings.append(
                f"API benchmark failed: {type(exc).__name__}: {exc}"
            )

        retained = selected.keep_scratch
        scratch_payload = {
            "path": str(root),
            "retained": retained,
            "auto_owned": auto_owned,
        }
        report = BenchmarkSuiteReport(
            schema_version=BENCHMARK_SUITE_SCHEMA_VERSION,
            created_at=datetime.now(UTC).isoformat(),
            tool_version=__version__,
            base=base,
            scratch_scan=scratch_scan,
            previews=previews,
            features=features,
            api=api,
            scratch=scratch_payload,
            warnings=warnings,
        )
    finally:
        if not selected.keep_scratch:
            shutil.rmtree(root, ignore_errors=True)

    return report


def write_benchmark_suite_report(
    report: BenchmarkSuiteReport,
    output: Path,
) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            report.to_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m weld_data_workbench.benchmark_suite",
        description=(
            "Run the comprehensive local benchmark suite. The suite can measure "
            "repository reads, scratch full/no-op scans, preview generation, "
            "handcrafted feature extraction, and in-process FastAPI throughput."
        ),
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=Path,
        required=True,
        help="Workspace directory or workbench.yaml path.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output JSON path. Defaults to workspace/reports/benchmark-suite.json.",
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=None,
        help=(
            "Optional parent directory for transient benchmark workspaces. "
            "A unique run directory is created underneath it."
        ),
    )
    parser.add_argument(
        "--repository-iterations",
        type=int,
        default=25,
        help="Repository list/detail iterations.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Repository/API sample page size.",
    )
    parser.add_argument(
        "--scratch-scan",
        action="store_true",
        help="Run a complete light scan and immediate no-op incremental scan.",
    )
    parser.add_argument(
        "--preview-samples",
        type=int,
        default=2,
        help="Number of deterministic samples used for preview benchmarks.",
    )
    parser.add_argument(
        "--feature-samples",
        type=int,
        default=4,
        help="Number of samples used for per-modality feature benchmarks.",
    )
    parser.add_argument(
        "--api-requests",
        type=int,
        default=32,
        help="Number of in-process API requests.",
    )
    parser.add_argument(
        "--api-concurrency",
        type=int,
        default=4,
        help="Maximum concurrent in-process API requests.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Worker count for scratch scans and feature extraction.",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Skip deterministic dataset snapshot calculation in the base benchmark.",
    )
    parser.add_argument(
        "--keep-scratch",
        action="store_true",
        help="Retain transient benchmark files for inspection.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    config = load_config(args.workspace)
    options = BenchmarkSuiteOptions(
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
    )
    report = run_benchmark_suite(
        config,
        options=options,
        scratch_root=args.scratch_root,
    )
    output = args.output or (config.reports_dir / "benchmark-suite.json")
    destination = write_benchmark_suite_report(report, output)
    summary = {
        "output": str(destination),
        "schema_version": report.schema_version,
        "snapshot_id": report.base.get("snapshot_id"),
        "scratch_scan_enabled": bool(report.scratch_scan.get("enabled")),
        "preview_enabled": bool(report.previews.get("enabled")),
        "features_enabled": bool(report.features.get("enabled")),
        "api_enabled": bool(report.api.get("enabled")),
        "warnings": report.warnings,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
