"""💾 Encrypted backup/restore for data_dir (AESGCM, manifest-verified)."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag

from octopus_browser.vault import SessionVault

BACKUP_VERSION = 1
ASSOCIATED_DATA = b"octopus-backup-v1"
KEY_ENV_DEFAULT = "OCTOPUS_BACKUP_KEY"
MAX_BYTES = 2_000_000_000


class BackupError(RuntimeError):
    """Ошибка бэкапа/восстановления (формат, ключ, целостность, назначение)."""


def generate_backup_key() -> str:
    return SessionVault.generate_key()


def _collect(data_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    if not data_dir.is_dir():
        raise BackupError(f"Нет каталога данных: {data_dir}")
    files: dict[str, bytes] = {}
    dirs: list[str] = []
    total = 0
    for path in sorted(data_dir.rglob("*"), key=lambda p: p.as_posix()):
        if path.is_symlink():
            continue
        if path.is_dir():
            dirs.append(path.relative_to(data_dir).as_posix())
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir).as_posix()
        blob = path.read_bytes()
        total += len(blob)
        if total > MAX_BYTES:
            raise BackupError(f"Каталог больше лимита {MAX_BYTES} байт")
        files[rel] = blob
    return files, dirs


def _pack(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for rel in sorted(files):
            blob = files[rel]
            info = tarfile.TarInfo(rel)
            info.size = len(blob)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(blob))
    return buffer.getvalue()


def _unpack(tar_blob: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_blob), mode="r:gz") as handle:
            for member in handle.getmembers():
                name = member.name
                if not name or name.startswith("/") or ".." in name.split("/"):
                    raise BackupError(f"Небезопасный путь в архиве: {name!r}")
                if not member.isfile():
                    continue
                extracted = handle.extractfile(member)
                if extracted is None:
                    raise BackupError(f"Не читается {name!r} в архиве")
                files[name] = extracted.read()
    except tarfile.TarError as exc:
        raise BackupError(f"Повреждённый tar: {exc}") from exc
    return files


def create_backup(data_dir: Path, out_path: Path, encoded_key: str) -> dict[str, Any]:
    if out_path.exists():
        raise BackupError(f"Файл уже существует, удалите вручную: {out_path}")
    if not encoded_key:
        raise BackupError("Не задан ключ бэкапа")
    files, dirs = _collect(data_dir)
    manifest = {rel: hashlib.sha256(blob).hexdigest() for rel, blob in files.items()}
    inner = {
        "v": BACKUP_VERSION,
        "created": datetime.now(timezone.utc).isoformat(),
        "files": manifest,
        "dirs": dirs,
        "tar_b64": base64.b64encode(_pack(files)).decode("ascii"),
    }
    try:
        vault = SessionVault(encoded_key)
        blob = vault.encrypt(json.dumps(inner, separators=(",", ":")).encode("utf-8"), associated_data=ASSOCIATED_DATA)
    except (ValueError, InvalidTag) as exc:
        raise BackupError(f"Шифрование не удалось: {exc}") from exc
    outer = {"v": BACKUP_VERSION, "blob": base64.b64encode(blob).decode("ascii")}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(outer), encoding="utf-8")
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return {"files": len(files), "bytes": sum(len(b) for b in files.values()),
            "dirs": len(dirs), "sha256": digest, "out": str(out_path)}


def _open_backup(backup_path: Path, encoded_key: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not encoded_key:
        raise BackupError("Не задан ключ бэкапа")
    try:
        outer = json.loads(backup_path.read_text(encoding="utf-8"))
        blob = base64.b64decode(outer["blob"].encode("ascii"), validate=True)
        vault = SessionVault(encoded_key)
        inner = json.loads(vault.decrypt(blob, associated_data=ASSOCIATED_DATA).decode("utf-8"))
    except (ValueError, KeyError, TypeError, binascii.Error, InvalidTag) as exc:
        raise BackupError(f"Неверный ключ или повреждённый бэкап ({type(exc).__name__})") from exc
    if not isinstance(inner, dict) or inner.get("v") != BACKUP_VERSION:
        raise BackupError("Неподдерживаемая версия бэкапа")
    try:
        files = _unpack(base64.b64decode(inner["tar_b64"].encode("ascii"), validate=True))
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise BackupError(f"Повреждённый архив ({type(exc).__name__})") from exc
    manifest = inner.get("files", {})
    if {rel: hashlib.sha256(blob).hexdigest() for rel, blob in files.items()} != manifest:
        raise BackupError("Манифест не сошёлся — архив повреждён")
    return inner, files


def verify_backup(backup_path: Path, encoded_key: str) -> dict[str, Any]:
    inner, files = _open_backup(backup_path, encoded_key)
    return {"files": len(files), "bytes": sum(len(b) for b in files.values()),
            "created": inner.get("created", ""), "dirs": len(inner.get("dirs", [])), "ok": True}


def restore_backup(backup_path: Path, to_dir: Path, encoded_key: str) -> dict[str, Any]:
    if to_dir.exists() and any(to_dir.iterdir()):
        raise BackupError(f"Каталог назначения не пуст (защита прода): {to_dir}")
    inner, files = _open_backup(backup_path, encoded_key)
    to_dir.mkdir(parents=True, exist_ok=True)
    for dirname in inner.get("dirs", []):
        if not dirname or dirname.startswith("/") or ".." in str(dirname).split("/"):
            raise BackupError(f"Небезопасный путь: {dirname!r}")
        (to_dir / dirname).mkdir(parents=True, exist_ok=True)
    for rel, blob in files.items():
        target = (to_dir / rel).resolve()
        try:
            target.relative_to(to_dir.resolve())
        except ValueError as exc:
            raise BackupError(f"Небезопасный путь: {rel!r}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return {"files": len(files), "bytes": sum(len(b) for b in files.values()), "to": str(to_dir)}
