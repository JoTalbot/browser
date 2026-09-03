"""🌍 Сеть: прокси-менеджер и VPN-интерфейс (WireGuard-адаптер)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

from octopus_browser.config import AppConfig


@dataclass
class ProxyEntry:
    """Один прокси-узел."""

    server: str  # scheme://host:port
    label: str = ""
    enabled: bool = True


@dataclass
class VPNSettings:
    """Настройки VPN (встраиваемый адаптер, например WireGuard)."""

    enabled: bool = False
    interface: str = "wg0"
    config_path: str = ""
    status: str = "disconnected"
    extra: dict = field(default_factory=dict)


class ProxyManager:
    """🔀 Ротация и проверка прокси."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.entries: List[ProxyEntry] = [
            ProxyEntry(server=p) for p in config.proxy_list
        ]
        self._cursor = 0

    def add(self, server: str, label: str = "") -> None:
        self.entries.append(ProxyEntry(server=server, label=label))

    def remove(self, server: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.server != server]
        return len(self.entries) < before

    def list(self) -> List[dict]:
        return [{"server": e.server, "label": e.label, "enabled": e.enabled}
                for e in self.entries]

    def current(self) -> Optional[str]:
        """Текущий прокси (первый включённый)."""
        for e in self.entries:
            if e.enabled:
                return e.server
        return None

    def rotate(self) -> Optional[str]:
        """🔄 Следующий включённый прокси (циклично)."""
        enabled = [e for e in self.entries if e.enabled]
        if not enabled:
            return None
        self._cursor = (self._cursor + 1) % len(enabled)
        return enabled[self._cursor].server

    def random_server(self) -> Optional[str]:
        enabled = [e for e in self.entries if e.enabled]
        return random.choice(enabled).server if enabled else None

    def health(self, server: str = "") -> dict:
        """🩺 Синтетическая проверка: резолв + HTTP (если доступен httpx)."""
        target = server or self.current()
        if not target:
            return {"ok": False, "error": "net proxy"}
        try:
            import httpx  # noqa: PLC0415

            with httpx.Client(proxy=target, timeout=8) as client:
                resp = client.get("http://check-host.net/ip", follow_redirects=True)
                return {"ok": resp.status_code == 200, "server": target,
                        "status": resp.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "server": target, "error": str(exc)}


class VPNManager:
    """🔒 VPN-интерфейс (реализация подключается к WireGuard/tailscale позже)."""

    def __init__(self) -> None:
        self.settings = VPNSettings()

    def connect(self) -> dict:
        """Подключение VPN (заглушка/интерфейс для интеграции)."""
        self.settings.status = "connected"
        self.settings.enabled = True
        return {"status": self.settings.status, "interface": self.settings.interface}

    def disconnect(self) -> dict:
        self.settings.status = "disconnected"
        self.settings.enabled = False
        return {"status": self.settings.status}

    def status(self) -> dict:
        return {"enabled": self.settings.enabled,
                "interface": self.settings.interface,
                "status": self.settings.status}
