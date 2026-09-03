"""⚙️ Конфигурация Octopus Browser."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass
class AppConfig:
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8090"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")).resolve())
    browser: str = os.getenv("BROWSER", "chromium")
    headless: bool = _env_bool("HEADLESS", True)
    default_profile: str = os.getenv("DEFAULT_PROFILE", "main")
    min_delay: float = float(os.getenv("HUMAN_MIN_DELAY", "0.4"))
    max_delay: float = float(os.getenv("HUMAN_MAX_DELAY", "1.6"))
    vision_api_url: str = os.getenv("VISION_API_URL", "")
    vision_api_key: str = os.getenv("VISION_API_KEY", "")
    vision_model: str = os.getenv("VISION_MODEL", "")
    max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "30"))
    api_key: str = os.getenv("OCTOPUS_API_KEY", "")
    max_concurrency: int = int(os.getenv("MAX_BROWSER_CONCURRENCY", "4"))
    navigation_timeout_ms: int = int(os.getenv("NAVIGATION_TIMEOUT_MS", "30000"))
    allowed_hosts: list[str] = field(default_factory=lambda: [h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()])
    proxy_list: list[str] = field(default_factory=lambda: [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()])

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def cookies_dir(self) -> Path:
        return self.data_dir / "cookies"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def proxy_first(self) -> str | None:
        return self.proxy_list[0] if self.proxy_list else None

    def proxy_target(self, index: int = 0) -> str | None:
        return self.proxy_list[index % len(self.proxy_list)] if self.proxy_list else None

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.profiles_dir, self.sessions_dir, self.cookies_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
