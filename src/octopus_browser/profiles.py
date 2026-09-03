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
        self._root = self.config.profiles_dir.resolve()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def validate_name(name: str) -> str:
        """Проверить имя профиля до любой работы с файловой системой."""
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("Имя профиля: только A-Z, 0-9, '_', '-' (до 64 символов)")
        return name

    def _safe_dir(self, name: str) -> Path:
        name = self.validate_name(name)
        path = (self._root / name).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Путь профиля выходит за пределы каталога профилей") from exc
        return path

    def _meta_path(self, name: str) -> Path:
        return self._safe_dir(name) / "profile.json"

    def _profile_dir(self, name: str) -> Path:
        return self._safe_dir(name)

    def list(self) -> List[dict]:
        out: List[dict] = []
        for meta in self._root.glob("*/profile.json"):
            try:
                out.append(json.loads(meta.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda p: p.get("name", ""))

    def create(self, name: str | None = None) -> dict:
        name = name or f"profile-{uuid.uuid4().hex[:8]}"
        self.validate_name(name)
        profile_dir = self._profile_dir(name)
        if profile_dir.exists():
            raise FileExistsError(f"Профиль '{name}' уже существует")
        profile_dir.mkdir(parents=True)
        meta = asdict(Profile(name=name, created=self._now(), dir=str(profile_dir)))
        self._meta_path(name).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return meta

    def get(self, name: str) -> Path:
        name = self.validate_name(name)
        profile_dir = self._profile_dir(name)
        profile_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self._meta_path(name)
        if not meta_path.exists():
            self.create(name)
        return profile_dir

    def delete(self, name: str) -> bool:
        name = self.validate_name(name)
        profile_dir = self._profile_dir(name)
        if not profile_dir.exists():
            return False
        shutil.rmtree(profile_dir)
        return True
