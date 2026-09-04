"""Central browser action policy used by the API and future agents."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ActionPolicy:
    allow_downloads: bool = False
    allow_uploads: bool = False
    auto_dismiss_dialogs: bool = True
    allow_new_tabs: bool = True
    max_navigation_bytes: int = 10_000_000

    def validate_navigation(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Навигация разрешена только на абсолютные HTTP(S) URL")

    def validate_upload(self, enabled: bool) -> None:
        if enabled and not self.allow_uploads:
            raise PermissionError("Загрузка файлов запрещена политикой браузера")

    def validate_download(self, enabled: bool) -> None:
        if enabled and not self.allow_downloads:
            raise PermissionError("Скачивание файлов запрещено политикой браузера")
