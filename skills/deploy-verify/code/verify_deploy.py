"""Постдеплойная проверка Octopus Browser (только стандартная библиотека)."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def fetch_json(url: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return {"status_code": resp.status, "payload": json.loads(resp.read().decode("utf-8"))}


def check_health(base_url: str) -> dict:
    data = fetch_json(base_url.rstrip("/") + "/health")
    payload = data["payload"]
    ok = data["status_code"] == 200 and payload.get("status") == "ok"
    return {"check": "health", "ok": ok, "service": payload.get("service"), "version": payload.get("version")}


def check_ready(base_url: str) -> dict:
    data = fetch_json(base_url.rstrip("/") + "/ready")
    return {"check": "ready", "ok": data["status_code"] == 200, "payload": data["payload"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Octopus Browser deployment")
    parser.add_argument("--base-url", default="http://127.0.0.1:8095")
    args = parser.parse_args()
    try:
        results = [check_health(args.base_url), check_ready(args.base_url)]
    except (OSError, ValueError) as exc:
        print(f"DEPLOY_VERIFY_FAILED: {exc}")
        return 1
    for item in results:
        print(f"{item['check']}: {'OK' if item['ok'] else 'FAIL'}")
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
