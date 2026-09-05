"""🔑 Менеджер сессий: TTL, revocation и authenticated encryption."""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from octopus_browser.config import AppConfig
from octopus_browser.profiles import ProfileManager
from octopus_browser.vault import SessionVault


class SessionManager:
    """Сохранение storage_state с версией схемы, TTL, revocation и шифрованием."""

    _SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
    SCHEMA_VERSION = 2

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_dirs()
        self._root = self.config.sessions_dir.resolve()
        self._vault = SessionVault(config.session_encryption_key) if config.session_encryption_key else None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not self._SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("Некорректный session_id")
        path = (self._root / f"{session_id}.session").resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Путь сессии выходит за пределы каталога сессий") from exc
        return path

    def _require_vault(self) -> SessionVault:
        if self._vault is None:
            raise RuntimeError("SESSION_ENCRYPTION_KEY не настроен")
        return self._vault

    def _expires(self, created: datetime) -> str | None:
        if self.config.session_ttl_seconds == 0:
            return None
        return (created + timedelta(seconds=self.config.session_ttl_seconds)).isoformat()

    def _serialize(self, payload: dict[str, Any]) -> bytes:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._require_vault().encrypt(raw, associated_data=str(payload["id"]).encode())

    def _deserialize(self, session_id: str, raw: bytes) -> dict[str, Any]:
        try:
            decoded = self._require_vault().decrypt(raw, associated_data=session_id.encode())
            payload = json.loads(decoded)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Повреждённая или недоступная сессия") from exc
        if not isinstance(payload, dict) or "storage_state" not in payload:
            raise ValueError("Повреждённая сессия")
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Неподдерживаемая версия схемы сессии")
        if payload.get("id") != session_id:
            raise ValueError("Идентификатор сессии не совпадает с файлом")
        return payload

    def _validate_live(self, payload: dict[str, Any]) -> None:
        if payload.get("revoked"):
            raise PermissionError("Сессия отозвана")
        expires = payload.get("expires")
        if expires and datetime.fromisoformat(expires) <= self._now():
            raise PermissionError("Срок действия сессии истёк")

    def save(self, storage_state: dict[str, Any], profile: str, label: str = "") -> str:
        ProfileManager.validate_name(profile)
        created = self._now()
        session_id = str(uuid.uuid4())
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "id": session_id,
            "profile": profile,
            "label": label,
            "created": created.isoformat(),
            "expires": self._expires(created),
            "revoked": False,
            "storage_state": storage_state,
        }
        path = self._path(session_id)
        path.write_bytes(self._serialize(payload))
        path.chmod(0o600)
        return session_id

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Сессия '{session_id}' не найдена")
        payload = self._deserialize(session_id, path.read_bytes())
        self._validate_live(payload)
        return payload["storage_state"]

    def revoke(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        payload = self._deserialize(session_id, path.read_bytes())
        payload["revoked"] = True
        path.write_bytes(self._serialize(payload))
        path.chmod(0o600)
        return True

    def purge_expired(self) -> int:
        removed = 0
        for path in self._root.glob("*.session"):
            try:
                session_id = path.stem
                payload = self._deserialize(session_id, path.read_bytes())
                expires = payload.get("expires")
                if expires and datetime.fromisoformat(expires) <= self._now():
                    path.unlink(missing_ok=True)
                    removed += 1
            except (OSError, ValueError, PermissionError):
                continue
        return removed

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self._root.glob("*.session"):
            try:
                payload = self._deserialize(path.stem, path.read_bytes())
                out.append({k: payload[k] for k in ("id", "profile", "label", "created", "expires", "revoked", "schema_version")})
            except (OSError, ValueError, PermissionError):
                continue
        return sorted(out, key=lambda s: s.get("created", ""), reverse=True)

    def export(self, session_id: str) -> str:
        path = self._path(session_id)
        payload = self._deserialize(session_id, path.read_bytes())
        self._validate_live(payload)
        return base64.b64encode(path.read_bytes()).decode()

    def import_session(self, b64: str, profile: str) -> str:
        ProfileManager.validate_name(profile)
        try:
            raw = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Некорректный формат импорта сессии") from exc
        if self._vault is None:
            raise RuntimeError("SESSION_ENCRYPTION_KEY не настроен")
        try:
            decoded = self._vault.decrypt(raw)
            payload = json.loads(decoded)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Некорректный формат импорта сессии") from exc
        if not isinstance(payload, dict) or "storage_state" not in payload:
            raise ValueError("Импорт сессии должен содержать storage_state")
        session_id = payload.get("id") or str(uuid.uuid4())
        if not isinstance(session_id, str):
            raise TypeError("Некорректный id сессии")
        self._path(session_id)
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["id"] = session_id
        payload["profile"] = profile
        payload["revoked"] = False
        payload["created"] = payload.get("created") or self._now().isoformat()
        created = datetime.fromisoformat(payload["created"])
        payload["expires"] = self._expires(created)
        path = self._path(session_id)
        path.write_bytes(self._serialize(payload))
        path.chmod(0o600)
        return session_id
