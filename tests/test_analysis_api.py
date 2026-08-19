from __future__ import annotations

from fastapi.testclient import TestClient

from weld_data_workbench.api.app import create_app
from weld_data_workbench.index.repository import DatasetRepository


def test_analysis_annotation_and_replay_api(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    samples = repository.list_samples(limit=20)
    sample_id = samples[0]["sample_id"]
    defect_id = next(record["sample_id"] for record in samples if not bool(record["is_good"]))

    with TestClient(create_app(config.workspace_root)) as client:
        annotation = client.put(
            "/api/annotations",
            json={
                "target_type": "sample",
                "sample_id": sample_id,
                "disposition": "accepted",
                "note": "api test",
                "tags": ["reviewed"],
            },
        )
        assert annotation.status_code == 200
        payload = annotation.json()
        assert payload["target_key"] == sample_id
        assert payload["revision"] >= 1

        fetched = client.get(f"/api/annotations/sample/{sample_id}")
        assert fetched.status_code == 200
        assert fetched.json()["disposition"] == "accepted"

        history = client.get(f"/api/annotations/sample/{sample_id}/history")
        assert history.status_code == 200
        assert history.json()

        listed = client.get("/api/annotations", params={"sample_id": sample_id})
        assert listed.status_code == 200
        assert listed.json()

        matches = client.get(f"/api/samples/{defect_id}/matches/good", params={"limit": 3})
        assert matches.status_code == 200
        assert len(matches.json()) <= 3

        distribution = client.get(
            "/api/analytics/distribution",
            params={"field": "category"},
        )
        assert distribution.status_code == 200
        assert distribution.json()["kind"] == "categorical"

        pivot = client.post(
            "/api/analytics/pivot",
            json={"row": "category", "column": "split", "measure": "count"},
        )
        assert pivot.status_code == 200
        assert pivot.json()["records"]

        replay = client.post(
            "/api/replay/plan",
            json={
                "sample_ids": [sample_id, defect_id],
                "interval_seconds": 0.1,
                "repeat": 1,
            },
        )
        assert replay.status_code == 200
        assert len(replay.json()["events"]) == 6

        schemas = client.get("/api/events/schema")
        assert schemas.status_code == 200
        assert schemas.json()["schema_version"] == 1


def test_analysis_api_validation(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    with TestClient(create_app(config.workspace_root)) as client:
        assert (
            client.get("/api/analytics/distribution", params={"field": "bad"}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/analytics/pivot",
                json={"row": "category", "filters": []},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/replay/plan",
                json={"sample_ids": ["missing-sample"]},
            ).status_code
            == 404
        )
        assert (
            client.put(
                "/api/annotations",
                json={"target_type": "sample", "disposition": "open"},
            ).status_code
            == 400
        )
