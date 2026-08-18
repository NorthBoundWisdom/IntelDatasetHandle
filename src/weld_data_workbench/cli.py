from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .config import init_workspace, load_config, save_config
from .index.builder import IndexBuilder
from .index.repository import DatasetRepository
from .io.archive import extract_tar_safely, inspect_tar
from .logging import configure_logging
from .previews.generator import PreviewGenerator
from .synthetic import generate_synthetic_dataset
from .validation.checks import run_validation

app = typer.Typer(
    name="weldtool",
    help="Local tooling for multimodal robotic-welding datasets.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()

WorkspaceOption = Annotated[
    Path,
    typer.Option("--workspace", "-w", help="Workspace directory or workbench.yaml path."),
]


def _config(workspace: Path):
    return load_config(workspace)


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    configure_logging(verbose)


@app.command("init")
def init_command(
    dataset_root: Annotated[
        Path, typer.Option("--dataset-root", help="Extracted raw dataset root.")
    ],
    workspace: WorkspaceOption,
    force: bool = typer.Option(False, help="Overwrite an existing workbench.yaml."),
) -> None:
    """Create a workspace configuration without modifying raw data."""
    config = init_workspace(dataset_root, workspace, force=force)
    console.print(f"[green]Created workspace[/green] {config.workspace_root}")
    console.print(f"Configuration: {config.config_path}")
    console.print(f"Dataset root: {config.dataset_root}")


@app.command("scan")
def scan_command(
    workspace: WorkspaceOption,
    workers: int | None = typer.Option(None, min=1, max=128),
    probe: str | None = typer.Option(None, help="none, light, or full"),
    sha256: bool = typer.Option(False, help="Compute SHA-256 for every asset; expensive."),
    persist_options: bool = typer.Option(
        False, help="Persist scan option overrides to workbench.yaml."
    ),
) -> None:
    """Discover samples, probe media, and atomically rebuild index.sqlite3."""
    config = _config(workspace)
    if workers is not None:
        config.scan.workers = workers
    if probe is not None:
        probe = probe.casefold()
        if probe not in {"none", "light", "full"}:
            raise typer.BadParameter("probe must be none, light, or full")
        config.scan.probe_mode = probe  # type: ignore[assignment]
    if sha256:
        config.scan.compute_sha256 = True
    if persist_options:
        save_config(config)

    builder = IndexBuilder(config)
    with _progress() as progress:
        task = progress.add_task("Indexing dataset", total=None)

        def update(completed: int, total: int, relpath: str) -> None:
            if progress.tasks[task].total is None:
                progress.update(task, total=total)
            progress.update(task, completed=completed, description=f"Indexing {relpath[-55:]}")

        summary = builder.build(workers=config.scan.workers, progress=update)

    table = Table(title="Index build")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Samples", f"{summary.sample_count:,}")
    table.add_row("Assets", f"{summary.asset_count:,}")
    table.add_row("Issues", f"{summary.issue_count:,}")
    table.add_row("Errors", f"{summary.error_count:,}")
    table.add_row("Warnings", f"{summary.warning_count:,}")
    table.add_row("Index", str(summary.index_path))
    console.print(table)
    for note in summary.discovery_notes:
        console.print(f"[dim]{note}[/dim]")


@app.command("stats")
def stats_command(
    workspace: WorkspaceOption,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Display indexed dataset statistics."""
    config = _config(workspace)
    repo = DatasetRepository(config.index_path, config.dataset_root)
    stats = repo.stats()
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    (config.reports_dir / "stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    if json_output:
        console.print_json(data=stats)
        return

    overview = Table(title="Dataset overview")
    overview.add_column("Metric")
    overview.add_column("Value", justify="right")
    overview.add_row("Samples", f"{stats['total_samples']:,}")
    overview.add_row("Sessions", f"{stats['total_sessions']:,}")
    overview.add_row("Assets", f"{stats['total_assets']:,}")
    overview.add_row("Indexed bytes", f"{stats['total_bytes'] / (1024**3):.2f} GiB")
    overview.add_row("Issues", f"{stats['total_issues']:,}")
    console.print(overview)

    for title, key in (
        ("Categories", "by_category"),
        ("Splits", "by_split"),
        ("Health", "by_health"),
    ):
        table = Table(title=title)
        table.add_column(title[:-1] if title.endswith("s") else title)
        table.add_column("Count", justify="right")
        for name, count in stats[key].items():
            table.add_row(str(name), f"{count:,}")
        console.print(table)

    if stats.get("audio_sample_rates_hz"):
        console.print("Audio sample rates:", stats["audio_sample_rates_hz"])


@app.command("validate")
def validate_command(
    workspace: WorkspaceOption,
    show: int = typer.Option(30, min=0, help="Maximum findings to print."),
) -> None:
    """Run dataset-level integrity and split checks."""
    config = _config(workspace)
    report = run_validation(config)
    severity = report.summary["validation_findings_by_severity"]
    style = "green" if report.passed else "red"
    console.print(
        f"[{style}]Validation {'passed' if report.passed else 'failed'}[/{style}] — "
        f"{severity['error']} errors, {severity['warning']} warnings, {severity['info']} info"
    )
    console.print(f"JSON: {config.reports_dir / 'validation.json'}")
    console.print(f"CSV:  {config.reports_dir / 'validation.csv'}")

    if show:
        table = Table(title="Validation findings")
        table.add_column("Severity")
        table.add_column("Code")
        table.add_column("Sample")
        table.add_column("Message")
        for finding in report.findings[:show]:
            table.add_row(
                finding.severity.value,
                finding.code,
                finding.sample_id or "—",
                finding.message,
            )
        console.print(table)

    if not report.passed:
        raise typer.Exit(code=2)


@app.command("inspect")
def inspect_command(
    workspace: WorkspaceOption,
    sample_id: Annotated[str, typer.Argument(help="Indexed sample ID.")],
) -> None:
    """Print complete indexed metadata for one sample."""
    config = _config(workspace)
    sample = DatasetRepository(config.index_path, config.dataset_root).get_sample(sample_id)
    if sample is None:
        console.print(f"[red]Unknown sample:[/red] {sample_id}")
        raise typer.Exit(1)
    console.print_json(data=sample)


@app.command("preview")
def preview_command(
    workspace: WorkspaceOption,
    sample_id: Annotated[str, typer.Option("--sample-id", help="Indexed sample ID.")],
    force: bool = typer.Option(False),
) -> None:
    """Generate bounded cached previews for one sample."""
    config = _config(workspace)
    bundle = PreviewGenerator(config).generate(sample_id, force=force)
    console.print_json(data=bundle.model_dump(mode="json"))


@app.command("export-index")
def export_index_command(
    workspace: WorkspaceOption,
    output: Annotated[Path, typer.Option("--output", "-o")],
    include_assets: bool = typer.Option(False, help="Embed assets/issues; best used with JSONL."),
) -> None:
    """Export indexed metadata to CSV, JSONL, or Parquet."""
    config = _config(workspace)
    repo = DatasetRepository(config.index_path, config.dataset_root)
    records: list[dict[str, object]] = []
    for row in repo.iter_samples(batch_size=1000):
        if include_assets:
            detail = repo.get_sample(str(row["sample_id"]))
            if detail:
                row = detail
        records.append(row)

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.casefold()
    if suffix in {".jsonl", ".ndjson"}:
        with output.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    elif suffix == ".parquet":
        try:
            pd.DataFrame(records).to_parquet(output, index=False)
        except ImportError as exc:
            raise typer.BadParameter("Parquet export requires the parquet extra") from exc
    else:
        if include_assets:
            raise typer.BadParameter("--include-assets requires JSONL/NDJSON output")
        pd.DataFrame(records).to_csv(output, index=False)
    console.print(f"Exported {len(records):,} records to {output}")


@app.command("features")
def features_command(
    workspace: WorkspaceOption,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    modalities: str = typer.Option("audio,video,sensor,image", help="Comma-separated modalities."),
    split: str | None = typer.Option(None),
    category: str | None = typer.Option(None),
    limit: int | None = typer.Option(None, min=1),
    workers: int | None = typer.Option(None, min=1, max=128),
) -> None:
    """Extract bounded handcrafted modality features."""
    from .features.pipeline import FeatureExtractor

    config = _config(workspace)
    output = output or (config.features_dir / "features.csv")
    selected = [item.strip() for item in modalities.split(",") if item.strip()]
    extractor = FeatureExtractor(config)
    with _progress() as progress:
        task = progress.add_task("Extracting features", total=None)

        def update(completed: int, total: int, sample_id: str) -> None:
            if progress.tasks[task].total is None:
                progress.update(task, total=total)
            progress.update(task, completed=completed, description=f"Features {sample_id}")

        summary = extractor.extract(
            output,
            modalities=selected,
            split=split,
            category=category,
            limit=limit,
            workers=workers,
            progress=update,
        )
    console.print_json(json=json.dumps(asdict(summary), ensure_ascii=False, default=str))


@app.command("baseline")
def baseline_command(
    workspace: WorkspaceOption,
    features: Annotated[Path | None, typer.Option("--features")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
) -> None:
    """Run a lightweight Isolation Forest anomaly baseline."""
    try:
        from .ml.tabular import run_isolation_forest_baseline
    except ImportError as exc:
        raise typer.BadParameter("Install the ML extra: pip install -e '.[ml]'") from exc

    config = _config(workspace)
    feature_path = features or (config.features_dir / "features.csv")
    destination = output_dir or (config.models_dir / "isolation_forest")
    result = run_isolation_forest_baseline(feature_path, destination)
    console.print_json(json=json.dumps(asdict(result), ensure_ascii=False, default=str))


@app.command("serve")
def serve_command(
    workspace: WorkspaceOption,
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765, min=1, max=65535),
    reload: bool = typer.Option(False),
) -> None:
    """Start the read-only FastAPI service."""
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter("Install the API extra: pip install -e '.[api]'") from exc
    from .api.app import create_app

    application = create_app(workspace)
    console.print(f"API documentation: http://{host}:{port}/docs")
    uvicorn.run(application, host=host, port=port, reload=reload)


@app.command("gui")
def gui_command(workspace: WorkspaceOption) -> None:
    """Launch the PySide6/QML dataset browser."""
    try:
        from .gui.app import run_gui
    except ImportError as exc:
        raise typer.BadParameter("Install the GUI extra: pip install -e '.[gui]'") from exc
    raise typer.Exit(run_gui(workspace))


@app.command("synthetic")
def synthetic_command(
    output: Annotated[Path, typer.Option("--output", "-o")],
    profile: str = typer.Option("tiny", help="tiny or taxonomy"),
    force: bool = typer.Option(False),
) -> None:
    """Generate a small multimodal fixture containing no Intel data."""
    summary = generate_synthetic_dataset(output, profile=profile, force=force)
    console.print_json(json=json.dumps(asdict(summary), ensure_ascii=False, default=str))


@app.command("archive-list")
def archive_list_command(
    archive: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    limit: int = typer.Option(200, min=1),
) -> None:
    """List tar/tar.gz members without extracting them."""
    table = Table(title=str(archive))
    table.add_column("Type")
    table.add_column("Bytes", justify="right")
    table.add_column("Name")
    count = 0
    total_bytes = 0
    for member in inspect_tar(archive):
        count += 1
        total_bytes += member.size_bytes
        if count <= limit:
            table.add_row(member.member_type, f"{member.size_bytes:,}", member.name)
    console.print(table)
    console.print(f"Members: {count:,}; uncompressed file bytes: {total_bytes / (1024**3):.2f} GiB")
    if count > limit:
        console.print(f"[dim]Showing first {limit:,} members.[/dim]")


@app.command("extract")
def extract_command(
    archive: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    destination: Annotated[Path, typer.Argument()],
    overwrite: bool = typer.Option(False),
) -> None:
    """Safely extract a tar archive, rejecting traversal and links."""
    with _progress() as progress:
        task = progress.add_task("Extracting", total=None)

        def update(count: int, member) -> None:
            progress.update(task, completed=count, description=f"Extracting {member.name[-55:]}")

        count = extract_tar_safely(archive, destination, overwrite=overwrite, progress=update)
    console.print(f"Extracted/visited {count:,} archive members into {destination.resolve()}")


@app.command("download")
def download_command(
    destination: Annotated[Path, typer.Option("--destination", "-d")],
    filename: str = typer.Option("intel_robotic_welding_dataset.tar.gz"),
) -> None:
    """Download the gated archive using the already authenticated Hugging Face account."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise typer.BadParameter(
            "Install the download extra: pip install -e '.[download]'"
        ) from exc

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(
        repo_id="IntelLabs/Intel_Robotic_Welding_Multimodal_Dataset",
        filename=filename,
        repo_type="dataset",
        local_dir=destination,
    )
    console.print(f"Downloaded to {path}")


if __name__ == "__main__":
    app()
