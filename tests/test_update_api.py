from fastapi.testclient import TestClient

from app.main import app


def test_update_status_has_orchestration_and_capabilities():
    client = TestClient(app)
    r = client.get("/api/update/status")
    assert r.status_code == 200
    data = r.json()
    assert "orchestration" in data
    assert "capabilities" in data
    assert "phase" in data["orchestration"]
    assert "deployment_mode" in data["capabilities"]


def test_update_start_requires_auth():
    client = TestClient(app)
    r = client.post("/api/update/start", json={})
    assert r.status_code == 401
