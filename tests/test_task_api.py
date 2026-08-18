from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from weld_data_workbench.api.app import create_app


def _wait(client: TestClient, task_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["state"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not complete")


def test_background_alignment_task_api(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    with TestClient(create_app(config.workspace_root)) as client:
        page = client.get("/api/samples", params={"limit": 1}).json()
        sample_id = page["items"][0]["sample_id"]
        submitted = client.post(f"/api/tasks/alignment/{sample_id}")
        assert submitted.status_code == 202
        task_id = submitted.json()["task_id"]

        finished = _wait(client, task_id)
        assert finished["state"] == "succeeded"
        assert finished["result"]["sample_id"] == sample_id

        listing = client.get("/api/tasks", params={"kind": "alignment.estimate"})
        assert listing.status_code == 200
        assert any(item["task_id"] == task_id for item in listing.json())


def test_task_api_rejects_unknown_sample_and_invalid_feature_request(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    with TestClient(create_app(config.workspace_root)) as client:
        assert client.post("/api/tasks/previews/not-a-sample").status_code == 404
        invalid = client.post("/api/tasks/features", json={"workers": 0})
        assert invalid.status_code == 400
        missing = client.get("/api/tasks/not-a-task")
        assert missing.status_code == 404
