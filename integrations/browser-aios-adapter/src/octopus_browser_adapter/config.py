"""Конфигурация адаптера без хранения секретов в репозитории."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, str(default))
    value = float(raw)
    if value < minimum:
        raise ValueError(f"{name} должен быть не меньше {minimum}")
    return value


def _int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default))
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} должен быть не меньше {minimum}")
    return value


@dataclass(frozen=True)
class ProfileEndpoint:
    """Адрес уже запущенного браузера; raw-профили и cookies сюда не попадают."""

    name: str
    cdp_url: str
    novnc_port: int


@dataclass(frozen=True)
class AdapterSettings:
    """Настройки CDP, consent gate и внешнего vision-провайдера."""

    primary_cdp_url: str = "http://127.0.0.1:9222"
    secondary_cdp_url: str = "http://127.0.0.1:9224"
    primary_novnc_port: int = 6080
    secondary_novnc_port: int = 6081
    action_require_approval: bool = True
    allow_external_vision: bool = False
    vision_provider: str = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "qwen/qwen3.8-27b"
    llm_balancer_url: str | None = None
    llm_balancer_model: str = "auto"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    llm_balancer_api_key: str | None = None
    request_timeout_seconds: float = 20.0
    max_image_bytes: int = 8 * 1024 * 1024
    aios_bridge_url: str = "http://127.0.0.1:9600"

    @classmethod
    def from_env(cls) -> AdapterSettings:
        provider = (
            os.getenv("OCTOPUS_BROWSER_VISION_PROVIDER", "gemini").strip().lower()
        )
        if provider not in {"gemini", "groq", "balancer", "auto"}:
            raise ValueError(
                "OCTOPUS_BROWSER_VISION_PROVIDER должен быть gemini, groq, balancer или auto"
            )
        balancer_url = (
            os.getenv("OCTOPUS_BROWSER_LLM_BALANCER_URL") or ""
        ).strip().rstrip("/") or None
        balancer_key = os.getenv("OCTOPUS_BROWSER_LLM_BALANCER_API_KEY") or None
        if balancer_key is None:
            if balancer_url and "api.groq.com" in balancer_url:
                balancer_key = os.getenv("GROQ_API_KEY") or os.getenv("ARENA_API_KEY")
            else:
                balancer_key = os.getenv("ARENA_API_KEY") or os.getenv("GROQ_API_KEY")
        return cls(
            primary_cdp_url=os.getenv(
                "OCTOPUS_BROWSER_PRIMARY_CDP_URL", cls.primary_cdp_url
            ),
            secondary_cdp_url=os.getenv(
                "OCTOPUS_BROWSER_SECONDARY_CDP_URL", cls.secondary_cdp_url
            ),
            primary_novnc_port=_int(
                "OCTOPUS_BROWSER_PRIMARY_NOVNC_PORT", cls.primary_novnc_port, 1
            ),
            secondary_novnc_port=_int(
                "OCTOPUS_BROWSER_SECONDARY_NOVNC_PORT", cls.secondary_novnc_port, 1
            ),
            action_require_approval=_bool(
                "OCTOPUS_BROWSER_ACTION_REQUIRE_APPROVAL", True
            ),
            allow_external_vision=_bool("OCTOPUS_BROWSER_ALLOW_EXTERNAL_VISION", False),
            vision_provider=provider,
            gemini_model=os.getenv("OCTOPUS_BROWSER_GEMINI_MODEL", cls.gemini_model),
            groq_model=os.getenv("OCTOPUS_BROWSER_GROQ_MODEL", cls.groq_model),
            llm_balancer_url=balancer_url,
            llm_balancer_model=os.getenv(
                "OCTOPUS_BROWSER_LLM_BALANCER_MODEL", cls.llm_balancer_model
            ),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            llm_balancer_api_key=balancer_key,
            request_timeout_seconds=_float(
                "OCTOPUS_BROWSER_VISION_TIMEOUT_SECONDS", 20.0, 1.0
            ),
            max_image_bytes=_int(
                "OCTOPUS_BROWSER_MAX_IMAGE_BYTES", 8 * 1024 * 1024, 1024
            ),
            aios_bridge_url=os.getenv(
                "OCTOPUS_AIOS_BRIDGE_URL", "http://127.0.0.1:9600"
            ).rstrip("/"),
        )

    def endpoint(self, profile: str) -> ProfileEndpoint:
        if profile == "primary":
            return ProfileEndpoint(
                profile, self.primary_cdp_url, self.primary_novnc_port
            )
        if profile == "secondary":
            return ProfileEndpoint(
                profile, self.secondary_cdp_url, self.secondary_novnc_port
            )
        raise ValueError("profile должен быть primary или secondary")

    def public_status(self) -> dict[str, object]:
        """Статус без значений секретов, cookies, URL страниц и аккаунтов."""
        configured = []
        if self.gemini_api_key:
            configured.append("gemini")
        if self.groq_api_key:
            configured.append("groq")
        if self.llm_balancer_url:
            configured.append("balancer")
        return {
            "vision_provider": self.vision_provider,
            "vision_models": {
                "gemini": self.gemini_model,
                "groq": self.groq_model,
                "balancer": self.llm_balancer_model,
            },
            "configured_vision_providers": configured,
            "llm_balancer_configured": self.llm_balancer_url is not None,
            "external_vision_enabled": self.allow_external_vision,
            "action_approval_required": self.action_require_approval,
            "aios_bridge_url": self.aios_bridge_url,
            "profiles": ["primary", "secondary"],
        }
