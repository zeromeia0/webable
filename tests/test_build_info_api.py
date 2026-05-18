from fastapi.testclient import TestClient

from app.main import app


def test_build_info_public_json():
    client = TestClient(app)
    r = client.get("/api/build-info")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert "commit" in data
    assert "build_id" in data
    assert "channel" in data
    assert "build_time" in data
    assert data["build_id"] == f"{data['version']}+{data['commit']}"
    assert data["deployment_mode"] in ("git", "image")
    assert "update_action_mode" in data
    assert isinstance(data["update_in_progress"], bool)
