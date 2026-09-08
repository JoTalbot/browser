"""🧪 Тесты шифрованного бэкапа: round-trip, tamper, ключи, защита назначения, CLI."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from octopus_browser.backup import (
    BackupError,
    create_backup,
    generate_backup_key,
    restore_backup,
    verify_backup,
)

KEY_A = generate_backup_key()
KEY_B = generate_backup_key()


def make_tree(root: Path) -> dict[str, bytes]:
    files = {
        "agent_jobs.json": b'{"jobs": []}',
        "aios_events.jsonl": b'{"v": 1}\n',
        "sessions/a.session": b"\x00\x01binary",
        "nested/deep/file.txt": "юникод ✓".encode(),
        "empty.txt": b"",
    }
    for rel, blob in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return files


def read_tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_roundtrip_and_verify(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    expected = make_tree(data)
    out = tmp_path / "full.obak"
    summary = create_backup(data, out, KEY_A)
    assert summary["files"] == len(expected) and len(summary["sha256"]) == 64
    assert "empty.txt" not in out.read_text()
    verified = verify_backup(out, KEY_A)
    assert verified["ok"] is True and verified["files"] == len(expected)
    restored = tmp_path / "restored"
    result = restore_backup(out, restored, KEY_A)
    assert result["files"] == len(expected)
    assert read_tree(restored) == expected


def test_tamper_and_wrong_key_fail(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    make_tree(data)
    out = tmp_path / "full.obak"
    create_backup(data, out, KEY_A)
    raw = json.loads(out.read_text(encoding="utf-8"))
    blob = bytearray(base64.b64decode(raw["blob"]))
    blob[20] ^= 0xFF
    raw["blob"] = base64.b64encode(bytes(blob)).decode("ascii")
    out.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BackupError, match="Неверный ключ|повреждён"):
        verify_backup(out, KEY_A)
    with pytest.raises(BackupError, match="Неверный ключ|повреждён"):
        restore_backup(out, tmp_path / "r2", KEY_A)
    out2 = tmp_path / "full2.obak"
    create_backup(data, out2, KEY_A)
    with pytest.raises(BackupError, match="Неверный ключ|повреждён"):
        verify_backup(out2, KEY_B)


def test_refuses_overwrite_and_nonempty(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "f.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "full.obak"
    create_backup(data, out, KEY_A)
    with pytest.raises(BackupError, match="уже существует"):
        create_backup(data, out, KEY_A)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("prod", encoding="utf-8")
    with pytest.raises(BackupError, match="не пуст"):
        restore_backup(out, busy, KEY_A)
    assert (busy / "keep.txt").read_text(encoding="utf-8") == "prod"


def test_empty_dirs_preserved(tmp_path) -> None:
    data = tmp_path / "data"
    (data / "empty1" / "nested-empty").mkdir(parents=True)
    (data / "lonely").mkdir()
    (data / "f.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "d.obak"
    assert create_backup(data, out, KEY_A)["dirs"] == 3
    restored = tmp_path / "r"
    restore_backup(out, restored, KEY_A)
    assert (restored / "empty1" / "nested-empty").is_dir()
    assert (restored / "lonely").is_dir()
    assert (restored / "f.txt").read_text(encoding="utf-8") == "x"


def test_empty_dir_and_missing_key(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "empty.obak"
    assert create_backup(data, out, KEY_A)["files"] == 0
    assert verify_backup(out, KEY_A)["files"] == 0
    with pytest.raises(BackupError, match="ключ"):
        create_backup(data, tmp_path / "nokey.obak", "")
    with pytest.raises(BackupError, match="Нет каталога"):
        create_backup(tmp_path / "missing", tmp_path / "x.obak", KEY_A)


def test_cli_cycle(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "backup.py"
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_text("cli", encoding="utf-8")
    key = subprocess.run([sys.executable, str(script), "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    assert len(base64.urlsafe_b64decode(key.encode("ascii"))) == 32
    import os

    env = dict(os.environ, OCTOPUS_BACKUP_KEY=key)
    out = tmp_path / "cli.obak"
    backup = subprocess.run([sys.executable, str(script), "backup", "--data-dir", str(data), "--out", str(out)],
                            capture_output=True, text=True, env=env, check=True)
    assert json.loads(backup.stdout)["files"] == 1
    verify = subprocess.run([sys.executable, str(script), "verify", "--in", str(out)],
                            capture_output=True, text=True, env=env, check=True)
    assert json.loads(verify.stdout)["ok"] is True
    restored = tmp_path / "cli-restored"
    subprocess.run([sys.executable, str(script), "restore", "--in", str(out), "--to-dir", str(restored)],
                   capture_output=True, text=True, env=env, check=True)
    assert (restored / "a.txt").read_text(encoding="utf-8") == "cli"
    assert key not in backup.stdout + verify.stdout
