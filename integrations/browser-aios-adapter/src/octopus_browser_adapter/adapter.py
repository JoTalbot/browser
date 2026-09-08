"""Публичный AIOS-facing интерфейс для browser automation."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from .bridge import AIOSBridgeClient
from .browser import CDPBrowserAdapter
from .config import AdapterSettings
from .vision import VisionRouter


class AIOSBrowserAdapter:
    """Композиция CDP browser + vision router для AIOS.

    Профили подключаются по имени `primary`/`secondary`; перенос cookies,
    storage state и каталогов Chrome намеренно не предоставляется.
    """

    def __init__(
        self,
        settings: AdapterSettings | None = None,
        browser: CDPBrowserAdapter | None = None,
        vision: VisionRouter | None = None,
        aios: AIOSBridgeClient | None = None,
    ) -> None:
        self.settings = settings or AdapterSettings.from_env()
        self.browser = browser or CDPBrowserAdapter(self.settings)
        self.vision = vision or VisionRouter(self.settings)
        self.aios = aios or AIOSBridgeClient(self.settings.aios_bridge_url)

    def capabilities(self) -> dict[str, object]:
        return {
            "adapter": "octopus-browser-aios",
            "profiles": ["primary", "secondary"],
            "operations": ["status", "observe", "vision-analyze", "navigate", "click", "fill"],
            "raw_profile_copy": False,
            "cookie_export": False,
            "action_approval_required": self.settings.action_require_approval,
        }

    def status(self) -> dict[str, object]:
        return {
            "profiles": self.browser.status(),
            "vision": self.settings.public_status(),
        }

    def aios_status(self) -> dict[str, object]:
        return self.aios.status()

    def observe(
        self, profile: str = "secondary", prompt: str = "Опиши интерфейс кратко."
    ) -> dict[str, object]:
        screenshot = self.browser.screenshot(profile)
        return {
            "profile": profile,
            "vision": self.vision.analyze_sync(
                screenshot, "image/png", prompt
            ).as_dict(),
        }

    def analyze_image(
        self,
        image_b64: str,
        mime_type: str = "image/png",
        prompt: str = "Опиши интерфейс кратко.",
    ) -> dict[str, object]:
        """Анализ переданного кадра через VisionRouter (для browser backend)."""
        try:
            image = base64.b64decode(image_b64.encode("ascii"), validate=True)
        except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
            raise ValueError("image_b64 должен быть корректным base64") from exc
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("mime_type: только image/png, image/jpeg, image/webp")
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt должен быть непустым и короче 4000 символов")
        return self.vision.analyze_sync(image, mime_type, prompt).as_dict()

    def action(
        self, profile: str, action: str, *, approved: bool = False, **kwargs: Any
    ) -> dict[str, object]:
        if action == "navigate":
            self.browser.navigate(profile, kwargs["url"], approved=approved)
        elif action == "click":
            self.browser.click(profile, kwargs["selector"], approved=approved)
        elif action == "fill":
            self.browser.fill(
                profile, kwargs["selector"], kwargs.get("text", ""), approved=approved
            )
        else:
            raise ValueError(f"неподдерживаемое действие: {action}")
        return {"ok": True, "profile": profile, "action": action}
