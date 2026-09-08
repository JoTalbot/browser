"""🔒 Per-profile leases for multi-agent coordination (persisted, expiring)."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("octopus.leases")


class LeaseConflict(Exception):
    """Профиль уже арендован другим держателем."""

    def __init__(self, current: dict[str, Any]) -> None:
        self.current = current
        super().__init__(f"Профиль занят: {current.get('holder')}")


class ProfileLeaseManager:
    """Аренда профилей с TTL и персистентностью (выживает рестарт, протухшие отмирают)."""

    def __init__(self, path: Path, clock: Callable[[], float] | None = None) -> None:
        self.path = path
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._leases: dict[str, dict[str, Any]] = self._load()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("leases load failed: %s", exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        now = self._clock()
        fresh = {}
        for profile, lease in raw.items():
            if isinstance(lease, dict) and float(lease.get("expires_wall", 0) or 0) > now:
                fresh[str(profile)] = lease
        if len(fresh) != len(raw):
            self._leases = fresh
            self._save_locked()
        return fresh

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._leases, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("leases save failed: %s", exc)

    def _expired(self, lease: dict[str, Any]) -> bool:
        try:
            return float(lease.get("expires_wall", 0) or 0) <= self._clock()
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _view(profile: str, lease: dict[str, Any]) -> dict[str, Any]:
        return {
            "lease_id": lease.get("lease_id", ""),
            "profile": profile,
            "holder": lease.get("holder", ""),
            "acquired_at": lease.get("acquired_at", ""),
            "expires_at": lease.get("expires_at", ""),
            "ttl_seconds": lease.get("ttl_seconds", 0),
        }

    def status(self, profile: str) -> dict[str, Any] | None:
        with self._lock:
            lease = self._leases.get(profile)
            if lease is None:
                return None
            if self._expired(lease):
                del self._leases[profile]
                self._save_locked()
                return None
            return self._view(profile, lease)

    def acquire(self, profile: str, holder: str, ttl_seconds: int) -> dict[str, Any]:
        if not holder or not holder.strip() or len(holder) > 128:
            raise ValueError("holder должен быть непустым и короче 128 символов")
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("ttl_seconds должен быть в диапазоне 1..86400")
        with self._lock:
            current = self._leases.get(profile)
            if current is not None and not self._expired(current):
                raise LeaseConflict(self._view(profile, current))
            now_wall = self._clock()
            lease = {
                "lease_id": uuid.uuid4().hex,
                "holder": holder.strip(),
                "acquired_at": self._now_iso(),
                "expires_at": datetime.fromtimestamp(now_wall + ttl_seconds, timezone.utc).isoformat(),
                "expires_wall": now_wall + ttl_seconds,
                "ttl_seconds": ttl_seconds,
            }
            self._leases[profile] = lease
            self._save_locked()
            return self._view(profile, lease)

    def release(self, lease_id: str) -> dict[str, Any] | None:
        with self._lock:
            for profile, lease in list(self._leases.items()):
                if lease.get("lease_id") == lease_id:
                    del self._leases[profile]
                    self._save_locked()
                    return self._view(profile, lease)
            return None

    def refresh(self, lease_id: str, ttl_seconds: int) -> dict[str, Any] | None:
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("ttl_seconds должен быть в диапазоне 1..86400")
        with self._lock:
            for profile, lease in list(self._leases.items()):
                if lease.get("lease_id") != lease_id:
                    continue
                if self._expired(lease):
                    del self._leases[profile]
                    self._save_locked()
                    return None
                now_wall = self._clock()
                lease["expires_wall"] = now_wall + ttl_seconds
                lease["expires_at"] = datetime.fromtimestamp(now_wall + ttl_seconds, timezone.utc).isoformat()
                lease["ttl_seconds"] = ttl_seconds
                self._save_locked()
                return self._view(profile, lease)
            return None

    def held_count(self) -> int:
        with self._lock:
            expired = [profile for profile, lease in self._leases.items() if self._expired(lease)]
            for profile in expired:
                del self._leases[profile]
            if expired:
                self._save_locked()
            return len(self._leases)
