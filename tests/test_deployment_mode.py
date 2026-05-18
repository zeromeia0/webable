"""Deployment mode detection and compose path validation."""

from pathlib import Path

import pytest

from app.services import build_info, deployment_mode, safe_compose


@pytest.fixture(autouse=True)
def _reset_caches():
    deployment_mode.clear_deployment_mode_cache()
    build_info.clear_build_identity_cache()
    yield
    deployment_mode.clear_deployment_mode_cache()
    build_info.clear_build_identity_cache()


def test_deployment_mode_override_image(monkeypatch):
    monkeypatch.setenv("WEBABLE_DEPLOYMENT_MODE", "image")
    deployment_mode.clear_deployment_mode_cache()
    assert deployment_mode.get_deployment_mode() == "image"


def test_deployment_mode_override_git(monkeypatch):
    monkeypatch.setenv("WEBABLE_DEPLOYMENT_MODE", "git")
    deployment_mode.clear_deployment_mode_cache()
    assert deployment_mode.get_deployment_mode() == "git"


def test_compose_path_rejects_parent_traversal(monkeypatch):
    monkeypatch.setenv("WEBABLE_DOCKER_COMPOSE_PATH", "/app/../../../etc/passwd")
    ok, msg = safe_compose.validate_compose_file_path()
    assert ok is False


def test_compose_path_accepts_project_file(monkeypatch):
    root = Path(__file__).resolve().parent.parent
    compose = root / "docker-compose.yml"
    assert compose.is_file()
    monkeypatch.setenv("WEBABLE_DOCKER_COMPOSE_PATH", str(compose))
    ok, msg = safe_compose.validate_compose_file_path()
    assert ok is True, msg


def test_build_info_dict_keys(monkeypatch):
    monkeypatch.setenv("WEBABLE_DEPLOYMENT_MODE", "image")
    monkeypatch.setenv("WEBABLE_EXPECT_EXTERNAL_UPDATER", "1")
    deployment_mode.clear_deployment_mode_cache()
    d = build_info.build_info_dict()
    for k in (
        "version",
        "commit",
        "build_id",
        "build_time",
        "channel",
        "deployment_mode",
        "auto_update_supported",
        "auto_update_enabled",
        "watchtower_expected",
        "update_action_supported",
        "update_action_mode",
        "update_in_progress",
    ):
        assert k in d
    assert d["deployment_mode"] == "image"
    assert d["watchtower_expected"] is True
    assert d["update_action_mode"] == "external_only"
