"""🌐 Запуск и управление браузером (Playwright)."""
from __future__ import annotations

import base64
import random
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from octopus_browser.config import AppConfig
from octopus_browser.policy import ActionPolicy
from octopus_browser.security import validate_external_url


class HumanPacer:
    """🕒 Имитация скорости реакции человека."""

    def __init__(self, min_delay: float = 0.4, max_delay: float = 1.6) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay

    def pause(self, multiplier: float = 1.0) -> None:
        delay = random.uniform(self.min_delay, self.max_delay) * multiplier
        time.sleep(delay)


class BrowserController:
    """Управление браузером через Playwright с policy и безопасной навигацией."""

    def __init__(self, config: AppConfig, profile_dir: Optional[Path] = None, proxy: Optional[str] = None) -> None:
        self.config = config
        self.profile_dir = profile_dir or config.profiles_dir / config.default_profile
        self.proxy = proxy or config.proxy_first
        self.pacer = HumanPacer(config.min_delay, config.max_delay)
        self.policy = ActionPolicy()
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started = False

    def start(self) -> None:
        """Запустить браузер с изолированным профилем и защитными обработчиками."""
        if self._started:
            return
        from playwright.sync_api import sync_playwright

        self.config.ensure_dirs()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        browser_type = getattr(self._pw, self.config.browser)
        proxy = {"server": self.proxy} if self.proxy else None
        self._context = browser_type.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.config.headless,
            proxy=proxy,
            viewport={"width": 1280, "height": 800},
            accept_downloads=self.policy.allow_downloads,
        )
        self._context.set_default_timeout(self.config.navigation_timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        self._context.on("page", self._on_page)
        self._context.on("dialog", self._on_dialog)
        self._context.route("**/*", self._network_guard)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._apply_page_timeouts()
        self._started = True

    def stop(self) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self._context = self._page = None
            self._started = False

    def goto(self, url: str) -> None:
        validate_external_url(url, self.config.allowed_hosts)
        self.policy.validate_navigation(url)
        self._require().goto(url, timeout=self.config.navigation_timeout_ms)
        self.pacer.pause()

    def screenshot(self, full_page: bool = False) -> str:
        raw = self._require().screenshot(full_page=full_page)
        return base64.b64encode(raw).decode()

    def click(self, selector: str) -> None:
        self.pacer.pause(0.4)
        self._require().click(selector, timeout=self.config.navigation_timeout_ms)
        self.pacer.pause()

    def fill(self, selector: str, text: str) -> None:
        self.pacer.pause(0.3)
        page = self._require()
        page.click(selector, timeout=self.config.navigation_timeout_ms)
        page.fill(selector, text, timeout=self.config.navigation_timeout_ms)
        self.pacer.pause()

    def scroll(self, amount: int = 400) -> None:
        self._require().mouse.wheel(0, amount)
        self.pacer.pause(0.5)

    def wait(self, seconds: float = 1.0) -> None:
        time.sleep(max(0.0, seconds))

    def eval_js(self, script: str) -> Any:
        return self._require().evaluate(script)

    def new_tab(self) -> None:
        self._page = self._context.new_page()
        self._apply_page_timeouts()
        self.pacer.pause()

    def close_tab(self) -> None:
        if self._page and len(self._context.pages) > 1:
            self._page.close()
            self._page = self._context.pages[-1]
            self._apply_page_timeouts()

    def url(self) -> str:
        return self._require().url

    def title(self) -> str:
        return self._require().title()

    def session_id(self) -> str:
        return str(uuid.uuid4())

    def _network_guard(self, route: Any) -> None:
        request_url = route.request.url
        try:
            validate_external_url(request_url, self.config.allowed_hosts)
        except ValueError:
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _on_page(self, page: Any) -> None:
        self._page = page
        self._apply_page_timeouts()

    def _on_dialog(self, dialog: Any) -> None:
        if self.policy.auto_dismiss_dialogs:
            dialog.dismiss()

    def _apply_page_timeouts(self) -> None:
        if self._page is not None:
            self._page.set_default_timeout(self.config.navigation_timeout_ms)
            self._page.set_default_navigation_timeout(self.config.navigation_timeout_ms)

    def _require(self) -> Any:
        if self._page is None:
            raise RuntimeError("Браузер не запущен: вызовите start()")
        return self._page
