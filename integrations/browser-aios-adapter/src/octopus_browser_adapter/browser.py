"""Подключение к уже запущенным Chrome через CDP без копирования профилей."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .config import AdapterSettings


class BrowserAdapterError(RuntimeError):
    """Базовая ошибка browser adapter."""


class ActionApprovalRequired(BrowserAdapterError):
    """Действие не прошло явный consent gate."""


class ProfileUnavailable(BrowserAdapterError):
    """Профиль не подключён или его CDP endpoint недоступен."""


@dataclass(frozen=True)
class ProfileStatus:
    profile: str
    connected: bool
    pages: int = 0
    hosts: tuple[str, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "profile": self.profile,
            "connected": self.connected,
            "pages": self.pages,
            "hosts": list(self.hosts),
        }
        if self.error:
            result["error"] = self.error
        return result


class CDPBrowserAdapter:
    """Адаптер к Chrome CDP.

    Он намеренно не умеет читать/копировать user-data-dir, Cookies, Local State
    или storage state. Сессия остаётся внутри уже запущенного браузера.
    """

    def __init__(
        self,
        settings: AdapterSettings,
        playwright_start: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._playwright_start = playwright_start
        self._playwright: Any = None
        self._connections: dict[str, tuple[Any, Any]] = {}

    def _ensure_playwright(self) -> Any:
        if self._playwright is not None:
            return self._playwright
        if self._playwright_start is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
        else:
            self._playwright = self._playwright_start()
        return self._playwright

    def _connect(self, profile: str) -> Any:
        try:
            endpoint = self.settings.endpoint(profile)
        except ValueError as exc:
            raise ProfileUnavailable(str(exc)) from exc
        if profile in self._connections:
            return self._connections[profile][1]
        try:
            browser = self._ensure_playwright().chromium.connect_over_cdp(
                endpoint.cdp_url, timeout=5000
            )
            if not browser.contexts:
                raise RuntimeError("CDP browser не содержит контекста")
            context = browser.contexts[0]
        except Exception as exc:
            raise ProfileUnavailable(f"{profile}: {type(exc).__name__}") from exc
        self._connections[profile] = (browser, context)
        return context

    @staticmethod
    def _host(url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    def status(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for profile in ("primary", "secondary"):
            try:
                context = self._connect(profile)
                pages = list(context.pages)
                hosts = tuple(
                    sorted(
                        {self._host(page.url) for page in pages if self._host(page.url)}
                    )
                )
                result.append(ProfileStatus(profile, True, len(pages), hosts).as_dict())
            except ProfileUnavailable as exc:
                result.append(ProfileStatus(profile, False, error=str(exc)).as_dict())
        return result

    def _page(self, profile: str, page_index: int = 0) -> Any:
        context = self._connect(profile)
        pages = list(context.pages)
        if not pages:
            raise ProfileUnavailable(f"{profile}: открытых вкладок нет")
        if page_index < 0 or page_index >= len(pages):
            raise ValueError("page_index вне диапазона")
        return pages[page_index]

    def screenshot(self, profile: str, page_index: int = 0) -> bytes:
        """Снять кадр вкладки; кадр остаётся в памяти вызывающего кода."""
        page = self._page(profile, page_index)
        return page.screenshot(type="png", full_page=False)

    def _require_approval(self, approved: bool) -> None:
        if self.settings.action_require_approval and not approved:
            raise ActionApprovalRequired("Действие требует approved=true")

    def navigate(
        self, profile: str, url: str, *, approved: bool = False, page_index: int = 0
    ) -> None:
        self._require_approval(approved)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("разрешены только абсолютные http/https URL")
        self._page(profile, page_index).goto(
            url, wait_until="domcontentloaded", timeout=30000
        )

    def click(
        self,
        profile: str,
        selector: str,
        *,
        approved: bool = False,
        page_index: int = 0,
    ) -> None:
        self._require_approval(approved)
        if not selector or len(selector) > 500:
            raise ValueError("некорректный selector")
        self._page(profile, page_index).click(selector, timeout=30000)

    def fill(
        self,
        profile: str,
        selector: str,
        text: str,
        *,
        approved: bool = False,
        page_index: int = 0,
    ) -> None:
        self._require_approval(approved)
        if not selector or len(selector) > 500:
            raise ValueError("некорректный selector")
        if len(text) > 20_000:
            raise ValueError("text слишком длинный")
        self._page(profile, page_index).fill(selector, text, timeout=30000)

    def disconnect(self) -> None:
        """Отключиться от CDP, не останавливая пользовательский Chrome."""
        self._connections.clear()
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
