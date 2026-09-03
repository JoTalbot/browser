"""🧪 Smoke- и unit-тесты Octopus Browser без реального Playwright."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from octopus_browser.agent import OctopusAgent
from octopus_browser.config import AppConfig
from octopus_browser.network import ProxyManager
from octopus_browser.profiles import ProfileManager
from octopus_browser.security import validate_external_url
from octopus_browser.sessions import SessionManager
from octopus_browser.vision import VisionDecision


def test_config_defaults(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    assert cfg.app_port > 0
    assert cfg.max_concurrency >= 1
    assert cfg.navigation_timeout_ms >= 1
    cfg.ensure_dirs()
    assert cfg.profiles_dir.exists()


def test_profile_manager(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    mgr = ProfileManager(cfg)
    meta = mgr.create("test")
    assert meta["name"] == "test"
    assert mgr.get("test").exists()
    assert any(p["name"] == "test" for p in mgr.list())
    assert mgr.delete("test") is True
    assert mgr.delete("test") is False


def test_profile_name_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        ProfileManager.validate_name("../escape")
    with pytest.raises(ValueError):
        ProfileManager.validate_name("a/b")


def test_session_id_rejects_path_traversal(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    mgr = SessionManager(cfg)
    with pytest.raises(ValueError):
        mgr.load("../escape")
    with pytest.raises(ValueError):
        mgr.load("a/b")


def test_session_roundtrip(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    mgr = SessionManager(cfg)
    sid = mgr.save({"cookies": [{"name": "x"}]}, "main", "test")
    assert mgr.load(sid) == {"cookies": [{"name": "x"}]}
    exported = mgr.export(sid)
    imported = mgr.import_session(exported, "secondary")
    assert imported == sid
    assert mgr.load(imported) == {"cookies": [{"name": "x"}]}


def test_api_authentication() -> None:
    from octopus_browser.api import app, config

    config.api_key = "test-key"
    client = TestClient(app)
    assert client.get("/octopus/info").status_code == 401
    assert client.get("/octopus/info", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/octopus/info", headers={"X-API-Key": "test-key"}).status_code == 200


def test_api_validates_navigation_url() -> None:
    from octopus_browser.api import app, config

    config.api_key = "test-key"
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}
    assert client.post("/navigate", json={"url": "file:///etc/passwd"}, headers=headers).status_code == 422
    assert client.post("/navigate", json={"url": "not-a-url"}, headers=headers).status_code == 422
    assert (
        client.post(
            "/navigate",
            json={"url": "https://example.com", "profile": "../x"},
            headers=headers,
        ).status_code
        == 422
    )


def test_external_url_rejects_non_global_address(monkeypatch) -> None:
    import socket

    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="частные/локальные"):
        validate_external_url("http://example.test")


def test_proxy_validation_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="credentials|Учётные"):
        ProxyManager.validate_server("http://user:pass@example.com:8080")


def test_agent_rejects_empty_task() -> None:
    class DummyController:
        def start(self): pass
        def stop(self): pass

    with pytest.raises(ValueError):
        OctopusAgent(AppConfig(), DummyController()).run(" ")


def test_agent_reports_step_limit() -> None:
    class DummyController:
        def start(self): pass
        def stop(self): pass
        def screenshot(self): return "image"
        def url(self): return "https://example.com"
        def wait(self, seconds): pass

    class DummyVision:
        def decide(self, image, task, history):
            return VisionDecision(action="wait", reason="test")

    run = OctopusAgent(AppConfig(), DummyController(), DummyVision()).run("test", max_steps=2)
    assert run.status == "limit"
    assert run.steps == 2


def test_modules_import() -> None:
    for mod in (
        "octopus_browser.core.launcher",
        "octopus_browser.sessions",
        "octopus_browser.cookies",
        "octopus_browser.network",
        "octopus_browser.vision",
        "octopus_browser.agent",
    ):
        importlib.import_module(mod)
