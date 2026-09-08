"""Запуск локального HTTP адаптера."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "octopus_browser_adapter.app:app",
        host=os.getenv("OCTOPUS_BROWSER_ADAPTER_HOST", "127.0.0.1"),
        port=int(os.getenv("OCTOPUS_BROWSER_ADAPTER_PORT", "9615")),
        reload=False,
    )


if __name__ == "__main__":
    main()
