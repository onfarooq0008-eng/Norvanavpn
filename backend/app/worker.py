"""Entry point: python -m app.worker"""
import asyncio
import logging

from app.config import load_config
from app.security.logging_setup import setup_logging
from app.services.refresh import RefreshWorker
from app.services.store import Store


def main() -> None:
    cfg = load_config()
    setup_logging([cfg.admin_secret, cfg.app_api_key])
    logging.getLogger("vpngate.worker").info("worker starting")
    worker = RefreshWorker(cfg, Store(cfg.db_path))
    try:
        asyncio.run(worker.loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
