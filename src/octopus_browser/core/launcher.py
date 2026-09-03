"""🌐 Запуск и управление браузером (Playwright).

Обеспечивает: изолированные контексты, прокси, человеческие задержки,
скриншоты для vision-агента.
"""

from __future__ import annotations

import base64
import random
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from octopus_browser.config import AppConfig


class HumanPacer:
    """🕒 Имитация скорости реакции человека."""

    def __init__(self, min_delay: float = 0.4, max_delay: float = 1.6) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay

    def pause(self, multiplier: float = 1.0) -> None:
        delay = random.uniform(self.min_delay, self.max_delay) * multiplier
        time.sleep(delay)

    def type_text(self, text: str, chunk: int = 3) -> None:
        """Печать текста «по кусочкам» — как человек."""
        import random as rnd
        for i in range(0, len(text), chunk):
            # эмулируем скорость ввода (здесь — без физического ввода)
            _ = text[i:i + chunk]
            time.sleep(rnd.uniform(0.02, 0.08))


class BrowserController:
    """Управление браузером через Playwright."""

    def __init__(self, config: AppConfig, profile_dir: Optional[Path] = None,
                 proxy: Optional[str] = None) -> None:
        self.config = config
        self.profile_dir = profile_dir or config.profiles_dir / config.default_profile
        self.proxy = proxy or config.proxy_first
        self.pacer = HumanPacer(config.min_delay, config.max_delay)
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Запустить браузер с изолированным профилем и контекстом."""
        from playwright.sync_api import sync_playwright  # ленивый импорт

        self.config.ensure_dirs()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
        browser_type = getattr(self._pw, self.config.browser)
        launch_args: dict[str, Any] = {"headless": self.config.headless}
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        # persistent context = изолированный мульти-профиль
        self._context = browser_type.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.config.headless,
            proxy=launch_args.get("proxy"),
            viewport={"width": 1280, "height": 800},
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self._pw:
            self._pw.stop()
        self._context = self._page = None

    # ---- actions ---------------------------------------------------------
    def goto(self, url: str) -> None:
        self._require().goto(url)
        self.pacer.pause()

    def screenshot(self, full_page: bool = False) -> str:
        """📸 Скриншот → base64 (для vision)."""
        raw = self._require().screenshot(full_page=full_page)
        return base64.b64encode(raw).decode()

    def click(self, selector: str) -> None:
        self.pacer.pause(0.4)
        self._require().click(selector)
        self.pacer.pause()

    def fill(self, selector: str, text: str) -> None:
        self.pacer.pause(0.3)
        page = self._require()
        page.click(selector)
        page.fill(selector, text)
        self.pacer.pause()

    def scroll(self, amount: int = 400) -> None:
        self._require().mouse.wheel(0, amount)
        self.pacer.pause(0.5)

    def wait(self, seconds: float = 1.0) -> None:
        time.sleep(seconds)

    def eval_js(self, script: str) -> Any:
        return self._require().evaluate(script)

    def new_tab(self) -> None:
        self._page = self._context.new_page()
        self.pacer.pause()

    def close_tab(self) -> None:
        if self._page and len(self._context.pages) > 1:
            self._page.close()
            self._page = self._context.pages[-1]

    # ---- introspection ---------------------------------------------------
    def url(self) -> str:
        return self._require().url

    def title(self) -> str:
        return self._require().title()

    def session_id(self) -> str:
        return str(uuid.uuid4())

    def _require(self) -> Any:
        if self._page is None:
            raise RuntimeError("Браузер не запущен: вызовите start()")
        return self._page
