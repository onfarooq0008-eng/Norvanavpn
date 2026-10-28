"""Entry point: python -m app.serve  (single uvicorn worker; binds to loopback by default)."""
import uvicorn

from app.config import load_config
from app.security.logging_setup import setup_logging


def main() -> None:
    cfg = load_config()
    setup_logging([cfg.admin_secret, cfg.app_api_key])
    uvicorn.run("app.main:create_app", factory=True, host=cfg.bind_host, port=cfg.bind_port, workers=1,
                access_log=False,           # no per-request logs => no client IPs in the journal
                proxy_headers=False,        # we read X-Forwarded-For ourselves, set only by our nginx
                server_header=False, timeout_keep_alive=5, limit_concurrency=200, log_config=None)


if __name__ == "__main__":
    main()
