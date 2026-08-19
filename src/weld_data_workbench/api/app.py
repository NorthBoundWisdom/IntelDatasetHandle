from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

try:
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.responses import FileResponse
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("Install the API extra: pip install -e '.[api]'") from exc

from ..alignment import estimate_sample_alignment
from ..analysis_services import AnalysisService
from ..annotations import AnnotationConflictError, AnnotationStore, issue_target_key
from ..config import load_config
from ..features.pipeline import FeatureExtractionCancelled, FeatureExtractor
from ..index.repository import DatasetRepository
from ..previews.generator import PreviewGenerator
from ..replay import DatasetReplayService, ReplayPlan, event_schema_bundle
from ..runtime_tasks import (
    TaskCancelledError,
    TaskContext,
    TaskManager,
    TaskQueueFullError,
    TaskState,
)
from .schemas import HealthResponse, PreviewResponse, SamplePage


def create_app(workspace_or_config: Path | str) -> FastAPI:
    config = load_config(Path(workspace_or_config))
    repository = DatasetRepository(config.index_path, config.dataset_root)
    previews = PreviewGenerator(config, repository)
    analysis = AnalysisService(repository)
    annotations = AnnotationStore(config.workspace_root / "overlays" / "annotations.sqlite3")
    replay = DatasetReplayService(repository)
    tasks = TaskManager(
        config.workspace_root / "jobs" / "tasks.sqlite3",
        max_workers=max(1, min(4, config.scan.workers)),
        max_queue=64,
    )

    def preview_task(payload: dict[str, Any], context: TaskContext) -> dict[str, Any]:
        context.report_progress(0, 1, "generating previews")
        bundle = previews.generate(
            str(payload["sample_id"]), force=bool(payload.get("force", False))
        )
        context.report_progress(1, 1, "previews ready")
        return {
            "sample_id": str(payload["sample_id"]),
            "bundle": bundle.model_dump(mode="json"),
        }

    def alignment_task(payload: dict[str, Any], context: TaskContext) -> dict[str, Any]:
        context.report_progress(0, 1, "estimating multimodal alignment")
        sample_id = str(payload["sample_id"])
        sample = repository.get_sample(sample_id)
        if sample is None:
            raise KeyError(f"Unknown sample: {sample_id}")
        report = estimate_sample_alignment(sample).to_dict()
        context.report_progress(1, 1, "alignment ready")
        return report

    def feature_task(payload: dict[str, Any], context: TaskContext) -> dict[str, Any]:
        modalities = payload.get("modalities", ["audio", "video", "sensor", "image"])
        if not isinstance(modalities, list) or not all(
            isinstance(value, str) for value in modalities
        ):
            raise ValueError("modalities must be a list of strings")
        output = config.features_dir / "tasks" / f"{context.task_id}.parquet"
        extractor = FeatureExtractor(config, repository)

        def progress(current: int, total: int, sample_id: str) -> None:
            context.store.report_progress(context.task_id, current, total, sample_id)

        try:
            summary = extractor.extract(
                output,
                modalities=modalities,
                split=str(payload["split"]) if payload.get("split") else None,
                category=str(payload["category"]) if payload.get("category") else None,
                limit=int(payload["limit"]) if payload.get("limit") is not None else None,
                workers=int(payload["workers"]) if payload.get("workers") is not None else None,
                progress=progress,
                force=bool(payload.get("force", False)),
                cancel_requested=lambda: context.cancel_requested,
            )
        except FeatureExtractionCancelled as exc:
            raise TaskCancelledError(str(exc)) from exc
        return {
            "output_path": str(summary.output_path),
            "samples_requested": summary.samples_requested,
            "samples_completed": summary.samples_completed,
            "samples_failed": summary.samples_failed,
            "feature_columns": summary.feature_columns,
            "jobs_requested": summary.jobs_requested,
            "jobs_reused": summary.jobs_reused,
            "jobs_executed": summary.jobs_executed,
            "jobs_failed": summary.jobs_failed,
        }

    tasks.register("preview.generate", preview_task)
    tasks.register("alignment.estimate", alignment_task)
    tasks.register("features.extract", feature_task)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            tasks.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="WeldDataWorkbench API",
        version="0.1.0",
        description="Read-only dataset access plus local derived-work task orchestration.",
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.repository = repository
    app.state.task_manager = tasks
    app.state.analysis_service = analysis
    app.state.annotation_store = annotations
    app.state.replay_service = replay

    def submit_task(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return tasks.submit(kind, payload).to_dict()
        except TaskQueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/api/samples/{sample_id}/matches/good")
    def good_matches(
        sample_id: str,
        limit: int = Query(default=5, ge=1, le=100),
        same_split: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            return analysis.good_matches(sample_id, limit=limit, same_split=same_split)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/samples/{sample_id}/alignment")
    def sample_alignment(sample_id: str) -> dict[str, Any]:
        """Synchronous compatibility endpoint for one alignment calculation."""

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
        """Synchronous compatibility endpoint; UI clients should prefer tasks."""

        try:
            bundle = previews.generate(sample_id, force=force)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Preview generation failed: {exc}"
            ) from exc
        return PreviewResponse(sample_id=sample_id, bundle=bundle.model_dump(mode="json"))

    @app.post("/api/tasks/previews/{sample_id}", status_code=202)
    def submit_previews(sample_id: str, force: bool = False) -> dict[str, Any]:
        if repository.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="Sample not found")
        return submit_task("preview.generate", {"sample_id": sample_id, "force": force})

    @app.post("/api/tasks/alignment/{sample_id}", status_code=202)
    def submit_alignment(sample_id: str) -> dict[str, Any]:
        if repository.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="Sample not found")
        return submit_task("alignment.estimate", {"sample_id": sample_id})

    @app.post("/api/tasks/features", status_code=202)
    def submit_features(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        safe_payload = dict(payload)
        if safe_payload.get("limit") is not None and int(safe_payload["limit"]) < 1:
            raise HTTPException(status_code=400, detail="limit must be positive")
        if safe_payload.get("workers") is not None:
            workers = int(safe_payload["workers"])
            if workers < 1 or workers > 128:
                raise HTTPException(status_code=400, detail="workers must be in [1, 128]")
        safe_payload.pop("output", None)
        safe_payload.pop("output_path", None)
        return submit_task("features.extract", safe_payload)

    @app.get("/api/tasks")
    def list_tasks(
        state: TaskState | None = None,
        kind: str | None = None,
        limit: int = Query(default=100, ge=1, le=5000),
    ) -> list[dict[str, Any]]:
        return [record.to_dict() for record in tasks.list(state=state, kind=kind, limit=limit)]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        record = tasks.get(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return record.to_dict()

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        record = tasks.cancel(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return record.to_dict()

    @app.get("/api/annotations")
    def list_annotations(
        target_type: str | None = None,
        sample_id: str | None = None,
        disposition: str | None = None,
        limit: int = Query(default=1000, ge=1, le=100_000),
    ) -> list[dict[str, Any]]:
        try:
            return [
                item.to_dict()
                for item in annotations.list(
                    target_type=target_type,
                    sample_id=sample_id,
                    disposition=disposition,
                    limit=limit,
                )
            ]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/annotations")
    def upsert_annotation(
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        target_type = str(payload.get("target_type", "sample")).strip().casefold()
        sample_id = str(payload.get("sample_id", "")).strip()
        if not sample_id:
            raise HTTPException(status_code=400, detail="sample_id is required")
        if repository.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="Sample not found")

        target_key = str(payload.get("target_key", "")).strip()
        if target_type == "sample":
            target_key = target_key or sample_id
        elif target_type == "issue" and not target_key:
            code = str(payload.get("code", "")).strip()
            if not code:
                raise HTTPException(
                    status_code=400,
                    detail="issue annotation requires target_key or code",
                )
            target_key = issue_target_key(
                sample_id,
                code,
                relpath=None
                if payload.get("relpath") is None
                else str(payload.get("relpath")),
                message=None
                if payload.get("message") is None
                else str(payload.get("message")),
            )

        raw_tags = payload.get("tags", [])
        if not isinstance(raw_tags, (list, tuple)):
            raise HTTPException(status_code=400, detail="tags must be a list")
        try:
            record = annotations.upsert(
                target_type=target_type,
                target_key=target_key,
                sample_id=sample_id,
                disposition=str(payload.get("disposition", "needs_review")),
                note=str(payload.get("note", "")),
                tags=[str(value) for value in raw_tags],
                updated_by=None
                if payload.get("updated_by") is None
                else str(payload.get("updated_by")),
                expected_revision=None
                if payload.get("expected_revision") is None
                else int(payload["expected_revision"]),
            )
        except AnnotationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record.to_dict()

    @app.get("/api/annotations/{target_type}/{target_key}")
    def get_annotation(target_type: str, target_key: str) -> dict[str, Any]:
        record = annotations.get(target_type, target_key)
        if record is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        return record.to_dict()

    @app.get("/api/annotations/{target_type}/{target_key}/history")
    def annotation_history(
        target_type: str,
        target_key: str,
        limit: int = Query(default=1000, ge=1, le=100_000),
    ) -> list[dict[str, Any]]:
        return annotations.history(target_type, target_key, limit=limit)

    @app.get("/api/analytics/distribution")
    def distribution(
        field: str,
        bins: int = Query(default=20, ge=1, le=100),
        q: str | None = Query(default=None, max_length=200),
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
    ) -> dict[str, Any]:
        try:
            return analysis.distribution(
                field,
                bins=bins,
                query=q,
                category=category,
                split=split,
                health=health,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/analytics/pivot")
    def pivot(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        filters = payload.get("filters", {})
        if not isinstance(filters, dict):
            raise HTTPException(status_code=400, detail="filters must be an object")
        try:
            return analysis.pivot(
                row=str(payload.get("row", "")),
                column=None
                if payload.get("column") is None
                else str(payload.get("column")),
                measure=str(payload.get("measure", "count")),
                value=None if payload.get("value") is None else str(payload.get("value")),
                query=None if filters.get("q") is None else str(filters.get("q")),
                category=None
                if filters.get("category") is None
                else str(filters.get("category")),
                split=None if filters.get("split") is None else str(filters.get("split")),
                health=None
                if filters.get("health") is None
                else str(filters.get("health")),
                limit=int(payload.get("limit", 5000)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/plan")
    def replay_plan(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        try:
            plan = ReplayPlan.model_validate(payload)
            events = replay.plan(plan)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "plan": plan.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }

    @app.get("/api/events/schema")
    def event_schemas() -> dict[str, Any]:
        return event_schema_bundle()

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
