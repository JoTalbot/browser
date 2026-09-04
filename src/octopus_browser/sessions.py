"""🔑 Менеджер сессий: безопасное хранение storage_state."""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from octopus_browser.config import AppConfig
from octopus_browser.profiles import ProfileManager


class SessionManager:
    """Сохранение storage_state с версией схемы и строгими идентификаторами."""

    _SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
    SCHEMA_VERSION = 1

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_dirs()
        self._root = self.config.sessions_dir.resolve()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not self._SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("Некорректный session_id")
        path = (self._root / f"{session_id}.json").resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Путь сессии выходит за пределы каталога сессий") from exc
        return path

    def save(self, storage_state: dict[str, Any], profile: str, label: str = "") -> str:
        ProfileManager.validate_name(profile)
        session_id = str(uuid.uuid4())
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "id": session_id,
            "profile": profile,
            "label": label,
            "created": self._now(),
            "storage_state": storage_state,
        }
        self._path(session_id).write_text(json.dumps(payload, ensure_ascii=False))
        return session_id

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Сессия '{session_id}' не найдена")
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or "storage_state" not in payload:
            raise ValueError("Повреждённая сессия")
        return payload["storage_state"]

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self._root.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                out.append({k: data[k] for k in ("id", "profile", "label", "created", "schema_version") if k in data})
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda s: s.get("created", ""), reverse=True)

    def export(self, session_id: str) -> str:
        return base64.b64encode(self._path(session_id).read_bytes()).decode()

    def import_session(self, b64: str, profile: str) -> str:
        ProfileManager.validate_name(profile)
        try:
            raw = base64.b64decode(b64, validate=True)
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Некорректный формат импорта сессии") from exc
        if not isinstance(payload, dict) or "storage_state" not in payload:
            raise ValueError("Импорт сессии должен содержать storage_state")
        session_id = payload.get("id") or str(uuid.uuid4())
        if not isinstance(session_id, str):
            raise ValueError("Некорректный id сессии")
        self._path(session_id)
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["id"] = session_id
        payload["profile"] = profile
        payload.setdefault("created", self._now())
        self._path(session_id).write_text(json.dumps(payload, ensure_ascii=False))
        return session_id
