"""🌍 Сеть: безопасное управление прокси и VPN-адаптером."""
from __future__ import annotations

import ipaddress
import random
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from octopus_browser.config import AppConfig


@dataclass
class ProxyEntry:
    """Один прокси-узел."""

    server: str
    label: str = ""
    enabled: bool = True


@dataclass
class VPNSettings:
    """Настройки VPN-адаптера."""

    enabled: bool = False
    interface: str = "wg0"
    config_path: str = ""
    status: str = "disconnected"
    extra: dict = field(default_factory=dict)


class ProxyManager:
    """🔀 Ротация, валидация и health-check прокси."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.entries = [ProxyEntry(server=p) for p in config.proxy_list]
        self._cursor = 0

    @staticmethod
    def validate_server(server: str) -> str:
        parsed = urlparse(server)
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
            raise ValueError("Прокси должен быть абсолютным URL с поддерживаемой схемой")
        if parsed.username or parsed.password:
            raise ValueError("Учётные данные прокси должны передаваться через secret manager")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Некорректный порт прокси") from exc
        if not port or not 1 <= port <= 65535:
            raise ValueError("Некорректный порт прокси")
        return server

    def add(self, server: str, label: str = "") -> None:
        self.validate_server(server)
        if any(e.server == server for e in self.entries):
            return
        self.entries.append(ProxyEntry(server=server, label=label))

    def remove(self, server: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.server != server]
        return len(self.entries) < before

    def list(self) -> list[dict]:
        return [{"server": e.server, "label": e.label, "enabled": e.enabled} for e in self.entries]

    def current(self) -> str | None:
        for entry in self.entries:
            if entry.enabled:
                return entry.server
        return None

    def rotate(self) -> str | None:
        enabled = [e for e in self.entries if e.enabled]
        if not enabled:
            return None
        self._cursor = (self._cursor + 1) % len(enabled)
        return enabled[self._cursor].server

    def random_server(self) -> str | None:
        enabled = [e for e in self.entries if e.enabled]
        return random.choice(enabled).server if enabled else None

    def health(self, server: str = "") -> dict:
        """🩺 Проверить прокси без раскрытия credentials."""
        target = server or self.current()
        if not target:
            return {"ok": False, "error": "no proxy configured"}
        try:
            target = self.validate_server(target)
            host = urlparse(target).hostname
            assert host is not None
            addresses = {info[4][0] for info in socket.getaddrinfo(host, urlparse(target).port, type=socket.SOCK_STREAM)}
            if any(not ipaddress.ip_address(addr).is_global for addr in addresses):
                return {"ok": False, "server": self._redact(target), "error": "non-global proxy address"}
            import httpx
            with httpx.Client(proxy=target, timeout=8) as client:
                resp = client.get("https://example.com", follow_redirects=True)
            return {"ok": resp.is_success, "server": self._redact(target), "status": resp.status_code}
        except Exception as exc:
            return {"ok": False, "server": self._redact(target), "error": str(exc)}

    @staticmethod
    def _redact(server: str) -> str:
        parsed = urlparse(server)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


class VPNManager:
    """🔒 Lifecycle interface for a host-managed VPN adapter."""

    def __init__(self) -> None:
        self.settings = VPNSettings()

    def connect(self) -> dict:
        self.settings.status = "connected"
        self.settings.enabled = True
        return {"status": self.settings.status, "interface": self.settings.interface}

    def disconnect(self) -> dict:
        self.settings.status = "disconnected"
        self.settings.enabled = False
        return {"status": self.settings.status}

    def status(self) -> dict:
        return {"enabled": self.settings.enabled, "interface": self.settings.interface, "status": self.settings.status}
