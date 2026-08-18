from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import FileResponse
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the API extra: pip install -e '.[api]'") from exc

from ..alignment import estimate_sample_alignment
from ..config import load_config
from ..index.repository import DatasetRepository
from ..previews.generator import PreviewGenerator
from .schemas import HealthResponse, PreviewResponse, SamplePage


def create_app(workspace_or_config: Path | str) -> FastAPI:
    config = load_config(Path(workspace_or_config))
    repository = DatasetRepository(config.index_path, config.dataset_root)
    previews = PreviewGenerator(config, repository)

    app = FastAPI(
        title="WeldDataWorkbench API",
        version="0.1.0",
        description="Read-only access to the local multimodal welding dataset index.",
    )
    app.state.config = config
    app.state.repository = repository

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            index_path=str(config.index_path),
            dataset_root=str(config.dataset_root),
            sample_count=repository.count_samples(),
        )

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return repository.meta()

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        return repository.stats()

    @app.get("/api/samples", response_model=SamplePage)
    def samples(
        q: str | None = Query(default=None, max_length=200),
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort_by: str = "relpath",
        descending: bool = False,
    ) -> SamplePage:
        try:
            items = repository.list_samples(
                query=q,
                category=category,
                split=split,
                health=health,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                descending=descending,
            )
            total = repository.count_samples(
                query=q,
                category=category,
                split=split,
                health=health,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return SamplePage(items=items, total=total, limit=limit, offset=offset)

    @app.get("/api/samples/{sample_id}")
    def sample(sample_id: str) -> dict[str, Any]:
        record = repository.get_sample(sample_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Sample not found")
        return record

    @app.get("/api/samples/{sample_id}/alignment")
    def sample_alignment(sample_id: str) -> dict[str, Any]:
        """Compute inspectable multimodal activity intervals and relative offsets."""

        record = repository.get_sample(sample_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Sample not found")
        try:
            return estimate_sample_alignment(record).to_dict()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Alignment estimation failed: {exc}",
            ) from exc

    @app.post("/api/samples/{sample_id}/previews", response_model=PreviewResponse)
    def generate_previews(sample_id: str, force: bool = False) -> PreviewResponse:
        try:
            bundle = previews.generate(sample_id, force=force)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Preview generation failed: {exc}"
            ) from exc
        return PreviewResponse(sample_id=sample_id, bundle=bundle.model_dump(mode="json"))

    @app.get("/api/samples/{sample_id}/media/{kind}/{ordinal}")
    def media(sample_id: str, kind: str, ordinal: int = 0) -> FileResponse:
        if kind not in {"video", "audio", "sensor", "image"}:
            raise HTTPException(status_code=400, detail="Unsupported media kind")
        path = repository.resolve_asset(sample_id, kind, ordinal)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(path, filename=path.name)

    @app.get("/api/issues")
    def issues(
        severity: str | None = None,
        code: str | None = None,
        limit: int = Query(default=1000, ge=1, le=100_000),
    ) -> list[dict[str, Any]]:
        return repository.issues(severity=severity, code=code, limit=limit)

    return app
