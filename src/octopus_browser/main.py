"""🚀 Точка входа: запуск API-сервера Octopus Browser."""

from __future__ import annotations

import logging

import uvicorn

from octopus_browser.config import AppConfig


def main() -> None:
    cfg = AppConfig()
    cfg.ensure_dirs()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    uvicorn.run("octopus_browser.api:app", host=cfg.app_host, port=cfg.app_port)


if __name__ == "__main__":
    main()
