#!/usr/bin/env python3
"""💾 CLI: encrypted backup/restore/verify for data_dir. Key via env/file, never logged."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from octopus_browser.backup import (
        KEY_ENV_DEFAULT,
        BackupError,
        create_backup,
        generate_backup_key,
        restore_backup,
        verify_backup,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from octopus_browser.backup import (
        KEY_ENV_DEFAULT,
        BackupError,
        create_backup,
        generate_backup_key,
        restore_backup,
        verify_backup,
    )


def _read_key(args: argparse.Namespace) -> str:
    if args.key_file:
        return Path(args.key_file).read_text(encoding="utf-8").strip()
    return os.getenv(args.key_env, "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted backup/restore for Octopus Browser data_dir")
    parser.add_argument("--key-env", default=KEY_ENV_DEFAULT)
    parser.add_argument("--key-file", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="Create encrypted backup")
    backup.add_argument("--data-dir", required=True)
    backup.add_argument("--out", required=True)
    restore = sub.add_parser("restore", help="Restore into an empty dir (refuses non-empty)")
    restore.add_argument("--in", dest="backup_path", required=True)
    restore.add_argument("--to-dir", required=True)
    verify = sub.add_parser("verify", help="Decrypt + check manifest without writing")
    verify.add_argument("--in", dest="backup_path", required=True)
    sub.add_parser("genkey", help="Print a fresh backup key (capture to secrets, never commit)")
    args = parser.parse_args(argv)
    try:
        if args.command == "genkey":
            print(generate_backup_key())
            return 0
        key = _read_key(args)
        if args.command == "backup":
            summary = create_backup(Path(args.data_dir), Path(args.out), key)
        elif args.command == "restore":
            summary = restore_backup(Path(args.backup_path), Path(args.to_dir), key)
        else:
            summary = verify_backup(Path(args.backup_path), key)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (BackupError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
