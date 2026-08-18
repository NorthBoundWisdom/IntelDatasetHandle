from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .alignment import estimate_sample_alignment, write_alignment_report
from .alignment_batch import (
    AlignmentBatchOptions,
    run_alignment_batch,
    write_alignment_batch_csv,
    write_alignment_batch_json,
    write_alignment_plots,
)
from .benchmark import run_repository_benchmark, write_benchmark_report
from .config import load_config
from .duplicates import scan_near_duplicates, write_near_duplicate_report
from .index.repository import DatasetRepository
from .io.paths import safe_slug
from .policy_compare import (
    compare_split_policies,
    load_predictions,
    load_verified_holdout_artifact,
    write_policy_comparison,
)
from .provenance import create_snapshot, load_snapshot, verify_snapshot
from .splits import audit_upstream_split, write_split_artifact

app = typer.Typer(
    name="weldinfra",
    help="Reproducibility, leakage-audit, benchmark, alignment, and experimental-split utilities.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()

WorkspaceOption = Annotated[
    Path,
    typer.Option("--workspace", "-w", help="Workspace directory or workbench.yaml path."),
]


@app.command("snapshot-create")
def snapshot_create(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    archive: Annotated[Path | None, typer.Option("--archive")] = None,
) -> None:
    """Create a deterministic dataset/index snapshot document."""
    config = load_config(workspace)
    destination = output or (config.reports_dir / "dataset-snapshot.json")
    snapshot = create_snapshot(config, archive_path=archive, output=destination)
    console.print_json(
        data={
            "snapshot_id": snapshot.snapshot_id,
            "output": str(destination.expanduser().resolve()),
            "counts": snapshot.payload["counts"],
        }
    )


@app.command("snapshot-verify")
def snapshot_verify(
    workspace: WorkspaceOption,
    snapshot_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    archive: Annotated[Path | None, typer.Option("--archive")] = None,
) -> None:
    """Verify that the current indexed dataset still matches a snapshot."""
    config = load_config(workspace)
    snapshot = load_snapshot(snapshot_file)
    verify_snapshot(config, snapshot, archive_path=archive)
    console.print(f"[green]Verified[/green] {snapshot.snapshot_id}")


@app.command("leakage-audit")
def leakage_audit(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Report upstream acquisition sessions and exact hashed assets crossing splits."""
    config = load_config(workspace)
    payload = audit_upstream_split(config).to_dict()
    if output is not None:
        destination = output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    console.print_json(data=payload)


@app.command("near-duplicates")
def near_duplicates_command(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    kinds: str = typer.Option("image,video", help="Comma-separated: image,video"),
    image_distance: int = typer.Option(4, min=0, max=64),
    video_distance: int = typer.Option(12, min=0, max=192),
    cross_split_only: bool = typer.Option(
        True,
        "--cross-split-only/--all-pairs",
        help="Limit candidates to assets whose owning samples use different upstream splits.",
    ),
    max_pairs: int = typer.Option(10_000, min=1),
) -> None:
    """Find cached perceptual near-duplicate candidates for leakage triage."""
    config = load_config(workspace)
    selected = tuple(item.strip() for item in kinds.split(",") if item.strip())
    report = scan_near_duplicates(
        config,
        kinds=selected,
        image_distance=image_distance,
        video_distance=video_distance,
        cross_split_only=cross_split_only,
        max_pairs=max_pairs,
    )
    destination = output or (config.reports_dir / "near-duplicates.json")
    write_near_duplicate_report(report, destination)
    payload = report.to_dict()
    payload["output"] = str(destination.expanduser().resolve())
    console.print_json(data=payload)


@app.command("split-create")
def split_create(
    workspace: WorkspaceOption,
    output: Annotated[Path, typer.Option("--output", "-o")],
    mode: str = typer.Option("holdout", help="holdout or kfold"),
    strategy: str = typer.Option("balanced", help="balanced or hash for holdout"),
    seed: int = typer.Option(0),
    train: float = typer.Option(0.7, min=0.0, max=1.0),
    validation: float = typer.Option(0.15, min=0.0, max=1.0),
    test: float = typer.Option(0.15, min=0.0, max=1.0),
    folds: int = typer.Option(5, min=2),
) -> None:
    """Create a deterministic session-disjoint experimental split artifact."""
    config = load_config(workspace)
    artifact = write_split_artifact(
        config,
        output,
        mode=mode,
        strategy=strategy,
        seed=seed,
        train=train,
        validation=validation,
        test=test,
        folds=folds,
    )
    console.print_json(
        data={
            "split_artifact_id": artifact["split_artifact_id"],
            "mode": artifact["mode"],
            "sessions": len(artifact["session_assignments"]),
            "samples": len(artifact["sample_assignments"]),
            "output": str(output.expanduser().resolve()),
        }
    )


@app.command("compare-splits")
def compare_splits_command(
    workspace: WorkspaceOption,
    predictions: Annotated[Path, typer.Option("--predictions", exists=True, dir_okay=False)],
    split_artifact: Annotated[Path, typer.Option("--split-artifact", exists=True, dir_okay=False)],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    score_col: str = typer.Option("anomaly_score"),
    label_col: str | None = typer.Option(None),
    upstream_threshold: float | None = typer.Option(None),
    experimental_threshold: float | None = typer.Option(None),
    bootstrap_iterations: int = typer.Option(500, min=0),
    bootstrap_seed: int = typer.Option(0),
) -> None:
    """Compare one prediction set under upstream and session-disjoint holdouts."""
    config = load_config(workspace)
    frame = load_predictions(predictions)
    artifact = load_verified_holdout_artifact(split_artifact)
    report = compare_split_policies(
        config,
        frame,
        artifact,
        score_col=score_col,
        label_col=label_col,
        upstream_threshold=upstream_threshold,
        experimental_threshold=experimental_threshold,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    destination = output or (config.reports_dir / "split-policy-comparison.json")
    write_policy_comparison(report, destination)
    report = dict(report)
    report["output"] = str(destination.expanduser().resolve())
    console.print_json(data=report)


@app.command("benchmark")
def benchmark_command(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    iterations: int = typer.Option(50, min=1, max=10_000),
    page_size: int = typer.Option(100, min=1, max=10_000),
    snapshot: bool = typer.Option(
        True,
        "--snapshot/--no-snapshot",
        help="Include the deterministic dataset snapshot ID in the report.",
    ),
) -> None:
    """Measure reproducible repository/read-path performance and emit JSON."""
    config = load_config(workspace)
    report = run_repository_benchmark(
        config,
        iterations=iterations,
        page_size=page_size,
        include_snapshot=snapshot,
    )
    destination = output or (config.reports_dir / "benchmark.json")
    write_benchmark_report(report, destination)
    payload = report.to_dict()
    payload["output"] = str(destination.expanduser().resolve())
    console.print_json(data=payload)


@app.command("alignment")
def alignment_command(
    workspace: WorkspaceOption,
    sample_id: Annotated[str, typer.Option("--sample-id")],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Estimate audio/video/sensor active intervals and relative timing for one sample."""
    config = load_config(workspace)
    sample = DatasetRepository(config.index_path, config.dataset_root).get_sample(sample_id)
    if sample is None:
        raise typer.BadParameter(f"Unknown sample: {sample_id}")
    report = estimate_sample_alignment(sample)
    destination = output or (config.reports_dir / "alignment" / f"{safe_slug(sample_id)}.json")
    write_alignment_report(report, destination)
    payload = report.to_dict()
    payload["output"] = str(destination.expanduser().resolve())
    console.print_json(data=payload)


@app.command("alignment-batch")
def alignment_batch_command(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
    split: Annotated[str | None, typer.Option("--split")] = None,
    health: Annotated[str | None, typer.Option("--health")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, max=64)] = 4,
    plots: bool = typer.Option(
        True,
        "--plots/--no-plots",
        help="Generate aggregate offset/spread/duration PNG diagnostics.",
    ),
) -> None:
    """Run dataset-wide alignment quality analysis and emit JSON/CSV/plots."""
    config = load_config(workspace)
    repository = DatasetRepository(config.index_path, config.dataset_root)
    report = run_alignment_batch(
        repository,
        options=AlignmentBatchOptions(
            query=query,
            category=category,
            split=split,
            health=health,
            limit=limit,
            workers=workers,
        ),
    )
    destination = output or (config.reports_dir / "alignment-batch.json")
    json_path = write_alignment_batch_json(report, destination)
    csv_path = write_alignment_batch_csv(report, destination.with_suffix(".csv"))
    plot_paths = (
        write_alignment_plots(report, destination.parent / "alignment-plots") if plots else []
    )
    console.print_json(
        data={
            "output": str(json_path),
            "csv": str(csv_path),
            "plots": [str(path) for path in plot_paths],
            "summary": report.summary,
        }
    )


if __name__ == "__main__":
    app()
