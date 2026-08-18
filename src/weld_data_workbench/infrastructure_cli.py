from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .config import load_config
from .provenance import create_snapshot, load_snapshot, verify_snapshot
from .splits import audit_upstream_split, write_split_artifact

app = typer.Typer(
    name="weldinfra",
    help="Reproducibility, leakage-audit, and experimental-split utilities.",
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


@app.command("split-create")
def split_create(
    workspace: WorkspaceOption,
    output: Annotated[Path, typer.Option("--output", "-o")],
    mode: str = typer.Option("holdout", help="holdout or kfold"),
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


if __name__ == "__main__":
    app()
