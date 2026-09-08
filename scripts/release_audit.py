#!/usr/bin/env python3
"""Static release gate for Octopus Browser.

The script deliberately has no third-party dependencies so the release gate can
run before the application environment is installed.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    pyproject = read("pyproject.toml")
    version_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not version_match:
        errors.append("pyproject.toml: missing project version")
    else:
        version = version_match.group(1)
        changelog = read("CHANGELOG.md")
        if version not in changelog:
            errors.append(f"CHANGELOG.md: version {version} is missing")
        api = read("src/octopus_browser/api.py")
        if f'version="{version}"' not in api:
            errors.append(f"api.py: FastAPI version is not {version}")

    required = [
        "AGENTS.md",
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/RELEASE.md",
        "docs/ROADMAP.md",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
        ".github/workflows/release.yml",
    ]
    for path in required:
        if not (ROOT / path).is_file():
            errors.append(f"missing required release file: {path}")

    forbidden = re.compile(r"(?:ghp_[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{20,}|-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----)")
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.name.endswith(".pyc"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if forbidden.search(text):
            errors.append(f"possible secret material found in {path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("release audit: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
