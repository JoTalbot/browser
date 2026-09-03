"""⚙️ Конфигурация Octopus Browser.

Все настройки читаются из переменных окружения (переопределяются по умолчанию).
Секреты (VISION_API_KEY и т.п.) — только из окружения, никогда из репозитория.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


@dataclass
class AppConfig:
    """Глобальная конфигурация приложения."""

    # 🖥️ Сервис
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8090"))

    # 📂 Данные
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data")).resolve()

    # 🌐 Браузер
    browser: str = os.getenv("BROWSER", "chromium")
    headless: bool = os.getenv("HEADLESS", "true").lower() in {"1", "true", "yes"}
    default_profile: str = os.getenv("DEFAULT_PROFILE", "main")

    # 🕒 Human-like pacing (задержки в секундах)
    min_delay: float = float(os.getenv("HUMAN_MIN_DELAY", "0.4"))
    max_delay: float = float(os.getenv("HUMAN_MAX_DELAY", "1.6"))

    # 🤖 ИИ-агент
    vision_api_url: str = os.getenv("VISION_API_URL", "")
    vision_api_key: str = os.getenv("VISION_API_KEY", "")
    vision_model: str = os.getenv("VISION_MODEL", "")
    max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "30"))

    # 🕵️ Прокси (список "scheme://host:port", разделённые запятыми)
    proxy_list: List[str] = field(default_factory=lambda: [
        p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()
    ])

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
        """Первый прокси из списка (или None)."""
        return self.proxy_list[0] if self.proxy_list else None

    def proxy_target(self, index: int = 0) -> str | None:
        """Прокси по индексу с безопасной ротацией."""
        if not self.proxy_list:
            return None
        return self.proxy_list[index % len(self.proxy_list)]

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.profiles_dir, self.sessions_dir,
                  self.cookies_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
