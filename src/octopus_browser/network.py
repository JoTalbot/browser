"""🌍 Сеть: безопасное управление прокси и VPN-адаптером."""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import random
import re
import socket
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from octopus_browser.config import AppConfig
from octopus_browser.vault import SessionVault

BASE_COOLDOWN_SECONDS = 30.0
MAX_COOLDOWN_SECONDS = 3600.0
HEALTH_CHECK_TIMEOUT_SECONDS = 8.0
HEALTH_CHECK_URL = "https://example.com"
SECRET_REF_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
PROXY_STATE_VERSION = 1
CREDENTIALS_STATE_VERSION = 1


def _utcnow() -> float:
    """⏱️ Единая точка времени (тесты подменяют через monkeypatch)."""
    return time.time()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class ProxyEntry:
    """Один прокси-узел c состоянием health-aware ротации."""

    server: str
    label: str = ""
    enabled: bool = True
    secret_ref: str = ""
    fails: int = 0
    disabled_until: float = 0.0
    last_check_ok: bool | None = None
    last_latency_ms: float | None = None

    def in_cooldown(self, now: float | None = None) -> bool:
        moment = _utcnow() if now is None else now
        return self.enabled and moment < self.disabled_until

    def eligible(self, now: float | None = None) -> bool:
        return self.enabled and not self.in_cooldown(now)

    def to_state(self) -> dict:
        return {
            "label": self.label,
            "enabled": self.enabled,
            "secret_ref": self.secret_ref,
            "fails": self.fails,
            "disabled_until": self.disabled_until,
            "last_check_ok": self.last_check_ok,
            "last_latency_ms": self.last_latency_ms,
        }

    @classmethod
    def from_state(cls, server: str, state: dict) -> ProxyEntry:
        last_ok = state.get("last_check_ok")
        last_latency = state.get("last_latency_ms")
        return cls(
            server=server,
            label=str(state.get("label", "")),
            enabled=bool(state.get("enabled", True)),
            secret_ref=str(state.get("secret_ref", "")),
            fails=max(0, int(state.get("fails", 0) or 0)),
            disabled_until=max(0.0, float(state.get("disabled_until", 0.0) or 0.0)),
            last_check_ok=last_ok if isinstance(last_ok, bool) else None,
            last_latency_ms=float(last_latency) if isinstance(last_latency, (int, float)) else None,
        )


@dataclass
class ProxyHealth:
    """Результат проверки узла (без секретов)."""

    ok: bool
    latency_ms: float = 0.0
    status_code: int = 0
    error: str = ""


@dataclass
class ProxyCredentials:
    """Логин/пароль прокси (только в памяти, никогда в логи)."""

    username: str
    password: str


class ProxyProvider(ABC):
    """Абстракция источника прокси (live-вендоры — отдельным решением, см. DECISIONS.md #1)."""

    name: str = "base"

    @abstractmethod
    def list_entries(self) -> list[ProxyEntry]:
        """Базовый набор узлов провайдера."""

    @abstractmethod
    def check(self, entry: ProxyEntry) -> ProxyHealth:
        """Активная проверка узла."""


class StaticListProvider(ProxyProvider):
    """Провайдер поверх фиксированного списка (по умолчанию — PROXY_LIST из конфига)."""

    name = "static"

    def __init__(self, servers: list[str], *, strict: bool = False) -> None:
        self.servers = list(servers)
        self.strict = strict

    def list_entries(self) -> list[ProxyEntry]:
        entries = []
        for server in self.servers:
            try:
                ProxyManager.validate_server(server)
            except ValueError:
                if self.strict:
                    raise
                continue
            entries.append(ProxyEntry(server=server))
        return entries

    def check(self, entry: ProxyEntry) -> ProxyHealth:
        try:
            ProxyManager.validate_server(entry.server)
            parsed = urlparse(entry.server)
            host = parsed.hostname
            assert host is not None
            addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)}
            if any(not ipaddress.ip_address(addr).is_global for addr in addresses):
                return ProxyHealth(ok=False, error="non-global proxy address")
            started = _utcnow()
            with httpx.Client(proxy=entry.server, timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
                resp = client.get(HEALTH_CHECK_URL, follow_redirects=True)
            latency_ms = (_utcnow() - started) * 1000.0
            if resp.is_success:
                return ProxyHealth(ok=True, latency_ms=latency_ms, status_code=resp.status_code)
            return ProxyHealth(ok=False, latency_ms=latency_ms, status_code=resp.status_code)
        except (OSError, ValueError, httpx.HTTPError) as exc:
            return ProxyHealth(ok=False, error=str(exc))


class MockProxyProvider(ProxyProvider):
    """Скриптованный провайдер без сети — тесты и dev (см. DECISIONS.md #1)."""

    name = "mock"

    def __init__(self, servers: list[str] | None = None) -> None:
        self._servers = list(servers) if servers else []
        self._script: dict[str, ProxyHealth] = {}
        self.calls: list[str] = []

    def list_entries(self) -> list[ProxyEntry]:
        return [ProxyEntry(server=server) for server in self._servers]

    def set_result(self, server: str, ok: bool, latency_ms: float = 5.0, error: str = "") -> None:
        self._script[server] = ProxyHealth(ok=ok, latency_ms=latency_ms, status_code=200 if ok else 0, error=error)

    def check(self, entry: ProxyEntry) -> ProxyHealth:
        self.calls.append(entry.server)
        return self._script.get(entry.server, ProxyHealth(ok=True, latency_ms=5.0, status_code=200))


class ProxyCredentialStore:
    """🔐 Шифрованное хранилище proxy-credentials (ref → username/password)."""

    def __init__(self, path: Path, vault: SessionVault | None) -> None:
        self._path = Path(path)
        self._vault = vault
        self._lock = threading.Lock()

    def _require_vault(self) -> SessionVault:
        if self._vault is None:
            raise RuntimeError("SESSION_ENCRYPTION_KEY не настроен")
        return self._vault

    def _read_blobs(self) -> dict[str, str]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ValueError("Файл proxy-credentials повреждён") from exc
        blobs = data.get("blobs", {})
        if not isinstance(blobs, dict):
            raise ValueError("Файл proxy-credentials повреждён")  # noqa: TRY004 — 400-семантика: повреждённый файл это ошибка данных
        return {str(key): str(value) for key, value in blobs.items()}

    def set(self, ref: str, username: str, password: str) -> None:
        ProxyManager.validate_secret_ref(ref)
        if not ref:
            raise ValueError("secret_ref не должен быть пустым")
        if not username or not password:
            raise ValueError("Логин и пароль прокси не должны быть пустыми")
        vault = self._require_vault()
        blob = vault.encrypt(
            json.dumps({"u": username, "p": password}).encode("utf-8"),
            associated_data=f"proxy-creds:{ref}".encode(),
        )
        with self._lock:
            blobs = self._read_blobs()
            blobs[ref] = base64.b64encode(blob).decode("ascii")
            _atomic_write_json(self._path, {"version": CREDENTIALS_STATE_VERSION, "blobs": blobs})

    def get(self, ref: str) -> ProxyCredentials:
        vault = self._require_vault()
        with self._lock:
            blobs = self._read_blobs()
        if ref not in blobs:
            raise ValueError(f"Credentials '{ref}' не найдены")
        try:
            raw = vault.decrypt(
                base64.b64decode(blobs[ref].encode("ascii")),
                associated_data=f"proxy-creds:{ref}".encode(),
            )
            data = json.loads(raw.decode("utf-8"))
            return ProxyCredentials(username=str(data["u"]), password=str(data["p"]))
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Credentials '{ref}' повреждены") from exc

    def delete(self, ref: str) -> bool:
        """Удаление не требует ключа: отзыв должен работать всегда."""
        with self._lock:
            blobs = self._read_blobs()
            if ref not in blobs:
                return False
            del blobs[ref]
            _atomic_write_json(self._path, {"version": CREDENTIALS_STATE_VERSION, "blobs": blobs})
            return True

    def has(self, ref: str) -> bool:
        """Проверка наличия (без расшифровки)."""
        try:
            with self._lock:
                return ref in self._read_blobs()
        except ValueError:
            return False


class ProxyManager:
    """🔀 Health-aware ротация, валидация и персистентность прокси."""

    def __init__(self, config: AppConfig, provider: ProxyProvider | None = None, vault: SessionVault | None = None) -> None:
        self.config = config
        self.provider = provider if provider is not None else StaticListProvider(config.proxy_list)
        if vault is None and config.session_encryption_key:
            vault = SessionVault(config.session_encryption_key)
        self._vault = vault
        self.credentials = ProxyCredentialStore(config.proxy_credentials_path, vault)
        self._lock = threading.Lock()
        self._cursor = 0
        self._rotations = 0
        self.entries: list[ProxyEntry] = []
        self._load_or_seed()

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

    @staticmethod
    def validate_secret_ref(ref: str) -> str:
        if not ref:
            return ""
        if not SECRET_REF_RE.match(ref):
            raise ValueError("secret_ref: латиница/цифры/._- длиной 1..64")
        return ref

    @staticmethod
    def redact_server(server: str) -> str:
        try:
            parsed = urlparse(server)
            if not parsed.hostname or not parsed.port:
                return "invalid"
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        except ValueError:
            return "invalid"

    def _read_state(self) -> dict | None:
        path = self.config.proxies_path
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
                raise ValueError("bad shape")  # noqa: TRY004 — corrupt state reseeds, это ошибка данных
            return data
        except ValueError:
            backup = path.with_name(path.name + ".corrupt")
            try:
                os.replace(path, backup)
            except OSError:
                pass
            return None

    def _load_or_seed(self) -> None:
        persisted = self._read_state()
        base = {entry.server: entry for entry in self.provider.list_entries()}
        if persisted is None:
            self.entries = list(base.values())
            return
        try:
            self._rotations = max(0, int(persisted.get("rotations", 0) or 0))
        except (ValueError, TypeError):
            self._rotations = 0
        saved = persisted.get("entries", {})
        merged: list[ProxyEntry] = []
        for server, entry in base.items():
            state = saved.get(server)
            if isinstance(state, dict):
                try:
                    merged.append(ProxyEntry.from_state(server, state))
                    continue
                except (ValueError, TypeError):
                    pass
            merged.append(entry)
        for server, state in saved.items():
            if server in base or not isinstance(state, dict):
                continue
            try:
                self.validate_server(server)
                merged.append(ProxyEntry.from_state(server, state))
            except (ValueError, TypeError):
                continue
        self.entries = merged

    def _save(self) -> None:
        with self._lock:
            payload = {
                "version": PROXY_STATE_VERSION,
                "provider": self.provider.name,
                "rotations": self._rotations,
                "entries": {entry.server: entry.to_state() for entry in self.entries},
            }
        _atomic_write_json(self.config.proxies_path, payload)

    def add(self, server: str, label: str | None = None, secret_ref: str | None = None) -> bool:
        """Upsert узла; True если создан новый (label: пустое не затирает; secret_ref: None не трогает, '' очищает)."""
        self.validate_server(server)
        if secret_ref is not None:
            self.validate_secret_ref(secret_ref)
        with self._lock:
            target = next((entry for entry in self.entries if entry.server == server), None)
            if target is None:
                self.entries.append(ProxyEntry(server=server, label=label or "", secret_ref=secret_ref or ""))
                created = True
            else:
                if label:
                    target.label = label
                if secret_ref is not None:
                    target.secret_ref = secret_ref
                created = False
        self._save()
        return created

    def remove(self, server: str) -> bool:
        with self._lock:
            before = len(self.entries)
            self.entries = [entry for entry in self.entries if entry.server != server]
            removed = len(self.entries) < before
        if removed:
            self._save()
        return removed

    def set_enabled(self, server: str, enabled: bool) -> bool:
        with self._lock:
            target = next((entry for entry in self.entries if entry.server == server), None)
            if target is None:
                return False
            target.enabled = enabled
            if enabled:
                target.disabled_until = 0.0
                target.fails = 0
        self._save()
        return True

    def list(self) -> list[dict]:
        now = _utcnow()
        with self._lock:
            snapshot = list(self.entries)
        return [
            {
                "server": entry.server,
                "label": entry.label,
                "enabled": entry.enabled,
                "secret_ref": entry.secret_ref,
                "has_credentials": bool(entry.secret_ref) and self.credentials.has(entry.secret_ref),
                "fails": entry.fails,
                "in_cooldown": entry.in_cooldown(now),
                "last_check_ok": entry.last_check_ok,
                "last_latency_ms": entry.last_latency_ms,
            }
            for entry in snapshot
        ]

    def _eligible(self, now: float) -> list[ProxyEntry]:
        with self._lock:
            return [entry for entry in self.entries if entry.eligible(now)]

    def _enabled(self) -> list[ProxyEntry]:
        with self._lock:
            return [entry for entry in self.entries if entry.enabled]

    def current(self) -> str | None:
        eligible = self._eligible(_utcnow())
        if eligible:
            return eligible[0].server
        enabled = self._enabled()
        return min(enabled, key=lambda entry: entry.fails).server if enabled else None

    def rotate(self) -> str | None:
        pool = self._eligible(_utcnow()) or sorted(self._enabled(), key=lambda entry: entry.fails)
        if not pool:
            return None
        with self._lock:
            self._cursor = (self._cursor + 1) % len(pool)
            chosen = pool[self._cursor].server
            self._rotations += 1
        self._save()
        return chosen

    def random_server(self) -> str | None:
        pool = self._eligible(_utcnow()) or self._enabled()
        return random.choice(pool).server if pool else None

    def report(self, server: str, ok: bool, latency_ms: float = 0.0) -> None:
        now = _utcnow()
        with self._lock:
            target = next((entry for entry in self.entries if entry.server == server), None)
            if target is None:
                return
            target.last_check_ok = ok
            target.last_latency_ms = latency_ms
            if ok:
                target.fails = 0
                target.disabled_until = 0.0
            else:
                target.fails += 1
                backoff = min(BASE_COOLDOWN_SECONDS * (2 ** (target.fails - 1)), MAX_COOLDOWN_SECONDS)
                target.disabled_until = now + backoff
        self._save()

    def refresh_health(self) -> dict:
        with self._lock:
            snapshot = [entry for entry in self.entries if entry.enabled]
        results = {}
        for entry in snapshot:
            health = self.provider.check(entry)
            self.report(entry.server, health.ok, health.latency_ms)
            results[self.redact_server(entry.server)] = {
                "ok": health.ok,
                "latency_ms": round(health.latency_ms, 2),
                "status_code": health.status_code,
                "error": health.error,
            }
        return {"provider": self.provider.name, "checked": len(results), "results": results}

    def health(self, server: str = "") -> dict:
        """🩺 Проверить прокси без раскрытия credentials."""
        target = server or (self.current() or "")
        if not target:
            return {"ok": False, "error": "no proxy configured"}
        try:
            self.validate_server(target)
        except ValueError as exc:
            return {"ok": False, "server": self.redact_server(target), "error": str(exc)}
        result = self.provider.check(ProxyEntry(server=target))
        self.report(target, result.ok, result.latency_ms)
        payload: dict = {"ok": result.ok, "server": self.redact_server(target)}
        if result.ok or not result.error:
            payload["status"] = result.status_code
        else:
            payload["error"] = result.error
        return payload

    def resolve(self, server: str) -> str:
        """Полный URL с credentials для транспорта (только в памяти, не логировать)."""
        with self._lock:
            target = next((entry for entry in self.entries if entry.server == server), None)
        if target is None:
            raise ValueError(f"Прокси '{self.redact_server(server)}' не найден")
        if not target.secret_ref:
            return target.server
        creds = self.credentials.get(target.secret_ref)
        parsed = urlparse(target.server)
        auth = f"{quote(creds.username, safe='')}:{quote(creds.password, safe='')}@"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{auth}{parsed.hostname or ''}{port}"

    def stats(self) -> dict:
        now = _utcnow()
        with self._lock:
            entries = list(self.entries)
            rotations = self._rotations
        return {
            "provider": self.provider.name,
            "total": len(entries),
            "enabled": sum(1 for entry in entries if entry.enabled),
            "in_cooldown": sum(1 for entry in entries if entry.in_cooldown(now)),
            "total_fails": sum(entry.fails for entry in entries),
            "rotations_total": rotations,
        }


@dataclass
class VPNSettings:
    """Настройки VPN-адаптера."""

    enabled: bool = False
    interface: str = "wg0"
    config_path: str = ""
    status: str = "disconnected"
    extra: dict = field(default_factory=dict)


class VPNManager:
    """🔒 Lifecycle interface for a host-managed VPN adapter (deferred — см. DECISIONS.md #2)."""

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
