from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from weld_data_workbench.api.app import create_app


def test_api_read_paths(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    client = TestClient(create_app(config.workspace_root))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["sample_count"] == 14

    page = client.get("/api/samples", params={"split": "test", "limit": 5})
    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 5
    sample_id = payload["items"][0]["sample_id"]

    detail = client.get(f"/api/samples/{sample_id}")
    assert detail.status_code == 200
    assert detail.json()["sample_id"] == sample_id

    media = client.get(f"/api/samples/{sample_id}/media/image/0")
    assert media.status_code == 200
