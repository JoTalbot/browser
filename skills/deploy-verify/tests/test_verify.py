"""Unit-тесты скилла deploy-verify без сети."""
from __future__ import annotations

import verify_deploy


def test_check_health_ok(monkeypatch) -> None:
    payload = {"status": "ok", "service": "octopus-browser", "version": "0.3.2"}
    monkeypatch.setattr(verify_deploy, "fetch_json", lambda url, timeout=5.0: {"status_code": 200, "payload": payload})
    result = verify_deploy.check_health("http://127.0.0.1:8095/")
    assert result["ok"] is True
    assert result["service"] == "octopus-browser"


def test_check_health_fail(monkeypatch) -> None:
    monkeypatch.setattr(verify_deploy, "fetch_json", lambda url, timeout=5.0: {"status_code": 500, "payload": {"status": "error"}})
    result = verify_deploy.check_health("http://127.0.0.1:8095")
    assert result["ok"] is False


def test_check_ready_ok(monkeypatch) -> None:
    monkeypatch.setattr(verify_deploy, "fetch_json", lambda url, timeout=5.0: {"status_code": 200, "payload": {"ready": True}})
    assert verify_deploy.check_ready("http://127.0.0.1:8095")["ok"] is True
