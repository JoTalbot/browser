"""🍪 Менеджер cookies: просмотр, установка, удаление, экспорт/импорт."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from octopus_browser.config import AppConfig


class CookieManager:
    """CRUD-операции над cookies активного контекста браузера."""

    def __init__(self, config: AppConfig, context: Any) -> None:
        self.config = config
        self.context = context

    def list(self, urls: list[str] | None = None) -> list[dict]:
        """📋 Cookies контекста."""
        return self.context.cookies(urls=urls or [])

    def set(self, name: str, value: str, url: str = "",
            domain: str = "", path: str = "/", expires: int = 0) -> None:
        """➕ Установить cookie."""
        cookie: dict[str, Any] = {"name": name, "value": value, "path": path}
        if url:
            cookie["url"] = url
        else:
            cookie["domain"] = domain
        if expires:
            cookie["expires"] = expires
        self.context.add_cookies([cookie])

    def delete(self, name: str, domain: str = "", path: str = "/") -> int:
        """🗑️ Удалить cookie по имени (и domain/path при задании).

        Возвращает количество удалённых cookies.
        """
        cookies = self.context.cookies()
        removed = 0
        kept: list[dict] = []
        for c in cookies:
            match = c["name"] == name
            if domain:
                match = match and c.get("domain", "") == domain
            if path:
                match = match and c.get("path", "/") == path
            if match:
                removed += 1
            else:
                kept.append(c)
        self.context.clear_cookies()
        if kept:
            self.context.add_cookies(kept)
        return removed

    def clear(self) -> None:
        """🧹 Очистить все cookies контекста."""
        self.context.clear_cookies()

    def export(self) -> str:
        """📤 Экспорт в JSON (для хранения/переноса).

        Формат: { "cookies": [...], "exported_at": "..." }
        """
        payload = {
            "cookies": self.context.cookies(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def import_cookies(self, data: str) -> int:
        """📥 Импорт из JSON. Возвращает количество загруженных cookies."""
        payload = json.loads(data)
        cookies = payload.get("cookies", payload if isinstance(payload, list) else [])
        if not isinstance(cookies, list):
            raise TypeError("Формат импорта: { 'cookies': [...] }")
        # привязываем сроки действия, если их нет
        for c in cookies:
            c.setdefault("expires", int(time.time()) + 3600 * 24 * 365)
        self.context.add_cookies(cookies)
        return len(cookies)
