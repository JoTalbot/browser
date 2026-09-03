"""🧪 Smoke-тесты каркаса Octopus Browser (без запуска Playwright)."""

from __future__ import annotations

import importlib

from octopus_browser.config import AppConfig
from octopus_browser.profiles import ProfileManager


def test_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.app_port > 0
    assert cfg.profiles_dir is not None
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


def test_modules_import() -> None:
    for mod in ("octopus_browser.core.launcher", "octopus_browser.sessions",
                "octopus_browser.cookies", "octopus_browser.network",
                "octopus_browser.vision", "octopus_browser.agent"):
        importlib.import_module(mod)
