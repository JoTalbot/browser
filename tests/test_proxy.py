"""🧪 Тесты ProxyProvider, vault-credentials, health-ротации и proxy-API (mock, без сети)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from octopus_browser import api as api_module
from octopus_browser.config import AppConfig
from octopus_browser.network import (
    MockProxyProvider,
    ProxyManager,
    StaticListProvider,
)
from octopus_browser.vault import SessionVault

PROXY_A = "http://127.0.0.1:18080"
PROXY_B = "http://127.0.0.1:18081"


def make_config(tmp_path, *, key: str = "") -> AppConfig:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    cfg.ensure_dirs()
    cfg.session_encryption_key = key
    return cfg


def make_manager(tmp_path, monkeypatch=None, *, servers=None, key: str = "") -> ProxyManager:
    cfg = make_config(tmp_path, key=key)
    provider = MockProxyProvider(servers if servers is not None else [PROXY_A, PROXY_B])
    vault = SessionVault(key) if key else None
    return ProxyManager(cfg, provider=provider, vault=vault)


@pytest.fixture()
def proxy_client(tmp_path, monkeypatch):
    key = SessionVault.generate_key()
    manager = make_manager(tmp_path, key=key)
    monkeypatch.setattr(api_module, "proxies", manager)
    api_module.app.dependency_overrides[api_module.protected] = lambda: None
    yield TestClient(api_module.app), manager
    api_module.app.dependency_overrides.clear()


def test_static_provider_skips_invalid_and_strict_raises() -> None:
    provider = StaticListProvider(["http://127.0.0.1:18080", "not-a-url"])
    assert [entry.server for entry in provider.list_entries()] == ["http://127.0.0.1:18080"]
    with pytest.raises(ValueError):
        StaticListProvider(["not-a-url"], strict=True).list_entries()


def test_mock_provider_script_and_calls() -> None:
    provider = MockProxyProvider([PROXY_A, PROXY_B])
    provider.set_result(PROXY_B, False, error="boom")
    entries = {entry.server: entry for entry in provider.list_entries()}
    assert provider.check(entries[PROXY_A]).ok is True
    failed = provider.check(entries[PROXY_B])
    assert failed.ok is False and failed.error == "boom"
    assert provider.calls == [PROXY_A, PROXY_B]


def test_credentials_roundtrip_and_delete(tmp_path) -> None:
    key = SessionVault.generate_key()
    manager = make_manager(tmp_path, key=key)
    manager.add(PROXY_A, secret_ref="node-a")
    manager.credentials.set("node-a", "user-a", "pass-a-секрет")
    creds = manager.credentials.get("node-a")
    assert (creds.username, creds.password) == ("user-a", "pass-a-секрет")
    assert manager.credentials.has("node-a") is True
    assert manager.credentials.delete("node-a") is True
    assert manager.credentials.has("node-a") is False


def test_credentials_require_vault(tmp_path) -> None:
    manager = make_manager(tmp_path)
    with pytest.raises(RuntimeError, match="SESSION_ENCRYPTION_KEY"):
        manager.credentials.set("r", "u", "p")
    with pytest.raises(RuntimeError, match="SESSION_ENCRYPTION_KEY"):
        manager.credentials.get("r")


def test_add_validates_server_and_ref(tmp_path) -> None:
    manager = make_manager(tmp_path)
    with pytest.raises(ValueError):
        manager.add("not-a-url")
    with pytest.raises(ValueError):
        manager.add(PROXY_A, secret_ref="bad ref!")
    manager.add(PROXY_A, label="a", secret_ref="ok_ref-1")
    assert manager.list()[0]["secret_ref"] == "ok_ref-1"


def test_rotation_prefers_healthy_and_recovers(tmp_path, monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("octopus_browser.network._utcnow", lambda: now[0])
    manager = make_manager(tmp_path)
    manager.report(PROXY_A, False)
    assert manager.rotate() == PROXY_B
    assert manager.rotate() == PROXY_B
    entry_a = next(entry for entry in manager.entries if entry.server == PROXY_A)
    assert entry_a.fails == 1 and entry_a.in_cooldown() is True
    now[0] += 31.0
    assert entry_a.in_cooldown() is False
    manager.report(PROXY_A, True, 3.0)
    assert entry_a.fails == 0
    assert manager.stats()["in_cooldown"] == 0


def test_cooldown_backoff_grows(tmp_path, monkeypatch) -> None:
    now = [2000.0]
    monkeypatch.setattr("octopus_browser.network._utcnow", lambda: now[0])
    manager = make_manager(tmp_path, servers=[PROXY_A])
    manager.report(PROXY_A, False)
    first = next(entry for entry in manager.entries if entry.server == PROXY_A).disabled_until
    assert first == 2030.0
    manager.report(PROXY_A, False)
    second = next(entry for entry in manager.entries if entry.server == PROXY_A).disabled_until
    assert second == 2060.0
    # Все в cooldown — деградированный fallback вместо None.
    assert manager.rotate() == PROXY_A


def test_resolve_injects_credentials_and_missing_raises(tmp_path) -> None:
    key = SessionVault.generate_key()
    manager = make_manager(tmp_path, key=key)
    manager.add(PROXY_A, secret_ref="node-a")
    manager.credentials.set("node-a", "user-a", "p@ss:word")
    resolved = manager.resolve(PROXY_A)
    assert resolved.startswith("http://user-a:p%40ss%3Aword@127.0.0.1:18080")
    with pytest.raises(ValueError, match="не найден"):
        manager.resolve("http://127.0.0.1:19999")
    manager.add(PROXY_B, secret_ref="ghost")
    with pytest.raises(ValueError, match="не найдены"):
        manager.resolve(PROXY_B)


def test_no_secrets_in_views(tmp_path) -> None:
    key = SessionVault.generate_key()
    manager = make_manager(tmp_path, key=key)
    manager.add(PROXY_A, secret_ref="node-a")
    manager.credentials.set("node-a", "secret-user", "secret-pass-123")
    blob = json.dumps(
        {"list": manager.list(), "health": manager.health(PROXY_A), "stats": manager.stats()},
        ensure_ascii=False,
    )
    assert "secret-user" not in blob and "secret-pass-123" not in blob


def test_persistence_roundtrip_and_corrupt_recovery(tmp_path) -> None:
    cfg = make_config(tmp_path)
    first = ProxyManager(cfg, provider=MockProxyProvider([PROXY_A]))
    first.add(PROXY_A, label="a")
    first.report(PROXY_A, False)
    assert cfg.proxies_path.is_file()
    second = ProxyManager(cfg, provider=MockProxyProvider([PROXY_A]))
    entry = next(item for item in second.list() if item["server"] == PROXY_A)
    assert entry["label"] == "a" and entry["fails"] == 1
    assert second.stats()["rotations_total"] == 0
    cfg.proxies_path.write_text("{broken", encoding="utf-8")
    third = ProxyManager(cfg, provider=MockProxyProvider([PROXY_A]))
    assert [item["server"] for item in third.list()] == [PROXY_A]
    assert cfg.proxies_path.with_name("proxies.json.corrupt").is_file()


def test_health_legacy_shapes(tmp_path) -> None:
    manager = make_manager(tmp_path, servers=[])
    assert manager.health() == {"ok": False, "error": "no proxy configured"}
    bad = manager.health("not-a-url")
    assert bad["ok"] is False and bad["server"] == "invalid"
    manager = make_manager(tmp_path)
    good = manager.health(PROXY_A)
    assert good["ok"] is True and good["server"] == PROXY_A and good["status"] == 200


def test_api_proxies_crud(proxy_client) -> None:
    client, _ = proxy_client
    created = client.post("/proxies", json={"server": "http://127.0.0.1:18082", "label": "c"})
    assert created.status_code == 201
    listed = client.get("/proxies")
    assert listed.status_code == 200
    assert "http://127.0.0.1:18082" in [item["server"] for item in listed.json()]
    rotated = client.post("/proxies/rotate")
    assert rotated.status_code == 200 and rotated.json()["server"]
    updated = client.post("/proxies", json={"server": "http://127.0.0.1:18082", "label": "c2"})
    assert updated.status_code == 200
    assert updated.json()["created"] is False and updated.json()["label"] == "c2"
    deleted = client.delete("/proxies", params={"server": "http://127.0.0.1:18082"})
    assert deleted.status_code == 200
    missing = client.delete("/proxies", params={"server": "http://127.0.0.1:18082"})
    assert missing.status_code == 404


def test_api_proxies_health_and_metrics(proxy_client) -> None:
    client, _ = proxy_client
    health = client.get("/proxies/health")
    assert health.status_code == 200
    assert health.json()["provider"] == "mock" and health.json()["checked"] == 2
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    for key in ("proxies_total", "proxies_enabled", "proxies_cooldown", "proxy_rotations_total"):
        assert key in metrics.json()


def test_api_proxies_add_invalid(proxy_client) -> None:
    client, _ = proxy_client
    resp = client.post("/proxies", json={"server": "not-a-url"})
    assert resp.status_code == 400


def test_api_proxies_credentials_roundtrip(proxy_client) -> None:
    client, manager = proxy_client
    stored = client.post("/proxies/credentials", json={"ref": "node-a", "username": "u", "password": "p"})
    assert stored.status_code == 201
    manager.add(PROXY_A, secret_ref="node-a")
    listed = client.get("/proxies")
    entry = next(item for item in listed.json() if item["server"] == PROXY_A)
    assert entry["has_credentials"] is True
    assert manager.resolve(PROXY_A) == "http://u:p@127.0.0.1:18080"


def test_api_proxies_credentials_no_vault(tmp_path, monkeypatch) -> None:
    manager = make_manager(tmp_path)
    monkeypatch.setattr(api_module, "proxies", manager)
    api_module.app.dependency_overrides[api_module.protected] = lambda: None
    try:
        client = TestClient(api_module.app)
        resp = client.post("/proxies/credentials", json={"ref": "r", "username": "u", "password": "p"})
        assert resp.status_code == 503
    finally:
        api_module.app.dependency_overrides.clear()
