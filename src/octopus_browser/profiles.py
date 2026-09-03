"""👥 Мульти-профили: изолированные user-data каталоги для браузера."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from octopus_browser.config import AppConfig

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass
class Profile:
    """Описание профиля."""

    name: str
    created: str
    last_used: str = ""
    dir: str = ""


class ProfileManager:
    """Управление изолированными профилями браузера."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_dirs()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _meta_path(self, name: str) -> Path:
        return self.config.profiles_dir / name / "profile.json"

    def list(self) -> List[dict]:
        """📋 Список всех профилей."""
        out: List[dict] = []
        for meta in self.config.profiles_dir.glob("*/profile.json"):
            try:
                out.append(json.loads(meta.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda p: p.get("name", ""))

    def create(self, name: str | None = None) -> dict:
        """➕ Создать профиль с уникальным именем."""
        name = name or f"profile-{uuid.uuid4().hex[:8]}"
        if not _NAME_RE.match(name):
            raise ValueError("Имя профиля: только A-Z, 0-9, '_', '-' (до 64 символов)")
        profile_dir = self.config.profiles_dir / name
        if profile_dir.exists():
            raise FileExistsError(f"Профиль '{name}' уже существует")
        profile_dir.mkdir(parents=True)
        meta = asdict(Profile(name=name, created=self._now(), dir=str(profile_dir)))
        self._meta_path(name).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return meta

    def get(self, name: str) -> Path:
        """🗂️ Каталог профиля (создаёт при отсутствии)."""
        profile_dir = self.config.profiles_dir / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self._meta_path(name)
        if not meta_path.exists():
            self.create(name)
        return profile_dir

    def delete(self, name: str) -> bool:
        """🗑️ Удалить профиль."""
        profile_dir = self.config.profiles_dir / name
        if not profile_dir.exists():
            return False
        shutil.rmtree(profile_dir)
        return True
