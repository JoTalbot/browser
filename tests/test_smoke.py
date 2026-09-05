"""🧪 Smoke- и unit-тесты Octopus Browser без реального Playwright."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from octopus_browser.agent import AgentState, OctopusAgent
from octopus_browser.config import AppConfig
from octopus_browser.network import ProxyManager
from octopus_browser.observability import AuditSink
from octopus_browser.profiles import ProfileManager
from octopus_browser.rate_limit import RateLimiter
from octopus_browser.security import validate_external_url
from octopus_browser.sessions import SessionManager
from octopus_browser.vault import SessionVault
from octopus_browser.vision import VisionDecision


def test_config_defaults(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    assert cfg.app_port > 0
    assert cfg.max_concurrency >= 1
    assert cfg.navigation_timeout_ms >= 1
    assert cfg.request_body_max_bytes >= 1024
    assert cfg.session_ttl_seconds >= 0
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


def test_session_requires_encryption_key(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    mgr = SessionManager(cfg)
    with pytest.raises(RuntimeError, match="SESSION_ENCRYPTION_KEY"):
        mgr.save({"cookies": []}, "main")


def test_session_roundtrip_encrypted_and_revocable(tmp_path) -> None:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    cfg.session_encryption_key = SessionVault.generate_key()
    cfg.session_ttl_seconds = 3600
    mgr = SessionManager(cfg)
    sid = mgr.save({"cookies": [{"name": "x"}]}, "main", "test")
    path = cfg.sessions_dir / f"{sid}.session"
    raw = path.read_bytes()
    assert b'"cookies"' not in raw
    assert (path.stat().st_mode & 0o777) == 0o600
    assert mgr.load(sid) == {"cookies": [{"name": "x"}]}
    exported = mgr.export(sid)
    imported = mgr.import_session(exported, "secondary")
    assert imported == sid
    assert mgr.load(imported) == {"cookies": [{"name": "x"}]}
    assert mgr.revoke(sid) is True
    with pytest.raises(PermissionError):
        mgr.load(sid)


def test_vault_tamper_is_rejected() -> None:
    vault = SessionVault(SessionVault.generate_key())
    encrypted = vault.encrypt(b"secret", associated_data=b"session-1")
    with pytest.raises(ValueError):
        vault.decrypt(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), associated_data=b"session-1")
    assert vault.decrypt(encrypted, associated_data=b"session-1") == b"secret"


def test_audit_sink_redacts_secrets(tmp_path) -> None:
    sink = AuditSink(tmp_path / "audit.jsonl")
    sink.write({"event": "auth", "api_key": "super-secret", "nested": {"token": "hidden"}, "path": "/health"})
    text = (tmp_path / "audit.jsonl").read_text()
    assert "super-secret" not in text
    assert "hidden" not in text
    assert "REDACTED" in text


def test_api_authentication() -> None:
    from octopus_browser.api import app, config

    config.api_key = "test-key"
    client = TestClient(app)
    assert client.get("/octopus/info").status_code == 401
    assert client.get("/octopus/info", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/octopus/info", headers={"X-API-Key": "test-key"}).status_code == 200


def test_api_readiness_and_metrics() -> None:
    from octopus_browser.api import app, config

    config.api_key = "test-key"
    client = TestClient(app)
    assert client.get("/ready").status_code == 200
    response = client.get("/metrics", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    assert "requests_total" in response.json()
    assert response.headers["x-request-id"]


def test_api_request_body_limit() -> None:
    from octopus_browser.api import app, config

    config.api_key = "test-key"
    original_limit = config.request_body_max_bytes
    config.request_body_max_bytes = 64
    client = TestClient(app)
    headers = {"X-API-Key": "test-key", "Content-Length": "65"}
    response = client.post("/sessions", json={"profile": "main"}, headers=headers)
    assert response.status_code == 413
    assert response.headers["x-request-id"]
    config.request_body_max_bytes = original_limit


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


def test_rate_limiter() -> None:
    limiter = RateLimiter(2, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


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
    assert run.state == AgentState.LIMIT
    assert run.steps == 2


def test_modules_import() -> None:
    for mod in (
        "octopus_browser.core.launcher",
        "octopus_browser.sessions",
        "octopus_browser.cookies",
        "octopus_browser.network",
        "octopus_browser.vision",
        "octopus_browser.agent",
        "octopus_browser.rate_limit",
        "octopus_browser.observability",
        "octopus_browser.vault",
    ):
        importlib.import_module(mod)
