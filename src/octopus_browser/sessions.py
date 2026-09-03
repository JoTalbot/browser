"""🔑 Менеджер сессий: сохранение, загрузка, экспорт/импорт состояния браузера."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from octopus_browser.config import AppConfig


class SessionManager:
    """Сохранение storage_state (cookies + localStorage + сессии) по профилям."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_dirs()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        return self.config.sessions_dir / f"{safe}.json"

    def save(self, storage_state: dict[str, Any], profile: str, label: str = "") -> str:
        """💾 Сохранить состояние сессии профиля. Возвращает session_id."""
        session_id = str(uuid.uuid4())
        payload = {
            "id": session_id,
            "profile": profile,
            "label": label,
            "created": self._now(),
            "storage_state": storage_state,
        }
        self._path(session_id).write_text(json.dumps(payload, ensure_ascii=False))
        return session_id

    def load(self, session_id: str) -> dict[str, Any]:
        """📂 Загрузить storage_state по session_id."""
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Сессия '{session_id}' не найдена")
        return json.loads(path.read_text())["storage_state"]

    def list(self) -> List[dict]:
        """📋 Список сессий."""
        out: List[dict] = []
        for path in self.config.sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                out.append({k: data[k] for k in ("id", "profile", "label", "created") if k in data})
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda s: s.get("created", ""), reverse=True)

    def export(self, session_id: str) -> str:
        """📤 Экспорт сессии в base64 (для передачи между серверами)."""
        return base64.b64encode(self._path(session_id).read_bytes()).decode()

    def import_session(self, b64: str, profile: str) -> str:
        """📥 Импорт сессии из base64."""
        try:
            raw = base64.b64decode(b64)
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Некорректный формат импорта сессии") from exc
        session_id = payload.get("id") or str(uuid.uuid4())
        self._path(session_id).write_text(json.dumps(payload, ensure_ascii=False))
        return session_id
