"""Public HTTP routes, shared admin page, and SSE use the same owned service."""

from dataclasses import replace
import json

import pytest
from starlette.testclient import TestClient

from src.app import build_app
from src.config import Settings
from src.errors import Unavailable
from tests.test_core import FakeEngine, image_bytes
from tests.seed import seed_token

ANN = {"X-Internal-Token": "test-token", "X-Requester-Username": "ann"}


@pytest.fixture
def settings(tmp_path):
    return seed_token(Settings(data_dir=tmp_path, admin_password="test-admin"), "test-token")


def upload(client):
    response = client.post("/api/files", content=image_bytes(), headers={**ANN, "X-Filename": "../../image.png"})
    assert response.status_code == 200
    return response.json()["file_id"]


def test_http_default_fast_ownership_cache_and_mode_discovery(settings):
    with TestClient(build_app(settings, FakeEngine())) as client:
        assert client.get("/api/modes", headers=ANN).json()["default"] == "accurate"
        file_id = upload(client)
        request = {"file_id": file_id, "regions": [[0, 0, 20, 20]]}
        result = client.post("/api/extract", json=request, headers=ANN)
        assert result.status_code == 200
        assert result.json()["mode"] == "accurate" and not result.json()["cached"]
        assert client.post("/api/extract", json=request, headers=ANN).json()["cached"]
        assert client.post("/api/extract", json={**request, "mode": "fast"}, headers=ANN).json()["mode"] == "fast"
        other = {**ANN, "X-Requester-Username": "bob"}
        assert client.post("/api/extract", json=request, headers=other).status_code == 404
        assert client.post("/api/extract", json=request, headers={}).status_code == 401
        assert client.get("/api/modes", headers={"X-Internal-Token": "test-token"}).status_code == 401


@pytest.mark.parametrize("body", [{}, {"file_id": "../x"}, {"file_id": "a" * 32, "mode": "auto"},
                                  {"file_id": "a" * 32, "regions": [[0, 0, 1.5, 3]]},
                                  {"file_id": "a" * 32, "owner": "bob"}])
def test_bad_request_schema(settings, body):
    with TestClient(build_app(settings, FakeEngine())) as client:
        assert client.post("/api/extract", json=body, headers=ANN).status_code == 422


def test_upload_validation_stream_boundary_errors_and_request_caps(settings):
    with TestClient(build_app(replace(settings, max_bytes=1000), FakeEngine())) as client:
        assert client.post("/api/files", content=b"x" * 1001, headers=ANN).status_code == 413
        assert client.post("/api/files", content=b"bad", headers=ANN).status_code == 400
        assert client.post("/api/extract", content=b"x" * 65537, headers=ANN).status_code == 413
        file_id = upload(client)
        bad = {"file_id": file_id, "regions": [[0, 0, 100, 100]]}
        assert client.post("/api/extract/stream", json=bad, headers=ANN).status_code == 400


def test_sse_region_results_and_final_input_order(settings):
    with TestClient(build_app(settings, FakeEngine())) as client:
        file_id = upload(client)
        body = {"file_id": file_id, "mode": "fast", "regions": [[0, 0, 20, 20], [20, 0, 40, 20]]}
        response = client.post("/api/extract/stream", json=body, headers=ANN)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["start", "region", "region", "complete"]
        assert events[0]["mode"] == "fast"
        assert [row["index"] for row in events[-1]["result"]["regions"]] == [0, 1]


def test_sse_error_is_sanitized_and_has_no_success_event(settings):
    class FailingEngine(FakeEngine):
        def recognize(self, crop, mode, timeout):
            raise RuntimeError("C:/private/path backend diagnostic")

    with TestClient(build_app(settings, FailingEngine())) as client:
        file_id = upload(client)
        response = client.post("/api/extract/stream", json={"file_id": file_id}, headers=ANN)
        assert "event: error" in response.text and "event: complete" not in response.text
        assert "private" not in response.text and "diagnostic" not in response.text


def test_model_unavailable_never_falls_back(settings):
    class MissingModel(FakeEngine):
        def fingerprint(self, mode):
            if mode == "accurate":
                raise Unavailable("The accurate model is missing.")
            return super().fingerprint(mode)

    with TestClient(build_app(settings, MissingModel())) as client:
        file_id = upload(client)
        assert client.post("/api/extract", json={"file_id": file_id}, headers=ANN).status_code == 503
        assert client.post("/api/extract", json={"file_id": file_id, "mode": "fast"}, headers=ANN).status_code == 200


def test_admin_password_live_limits_usage_and_playground_mode(settings):
    with TestClient(build_app(settings, FakeEngine())) as client:
        pw = {"X-Admin-Password": "test-admin"}
        assert client.get("/admin/status").status_code == 401
        status = client.get("/admin/status", headers=pw).json()
        assert status["service"] == "Lens"
        fields = status["playground"]["operations"][0]["fields"]
        mode = next(field for field in fields if field["key"] == "mode")
        assert mode["default"] == "accurate" and mode["type"] == "select"
        assert client.get("/admin/").status_code == 200
        assert client.put("/admin/settings", headers=pw, json={"values": {"max_regions": 1}}).status_code == 200
        file_id = upload(client)
        request = {"file_id": file_id, "regions": [[0, 0, 20, 20], [20, 0, 40, 20]]}
        assert client.post("/api/extract", json=request, headers=ANN).status_code == 400
        usage = client.get("/admin/status", headers=pw).json()["usage"]
        assert usage["calls"] == 1 and usage["errors"] == 1
        assert client.put("/admin/settings", headers=pw, json={"values": {"max_regions": 0}}).status_code == 422


def test_admin_off_and_exposed_unauthenticated_start_refused(tmp_path):
    with TestClient(build_app(Settings(data_dir=tmp_path), FakeEngine())) as client:
        assert client.get("/admin/").status_code in (404, 405)
    with pytest.raises(ValueError, match="token"):
        build_app(Settings(data_dir=tmp_path, host="0.0.0.0"), FakeEngine())
