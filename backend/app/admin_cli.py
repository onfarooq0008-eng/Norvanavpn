"""Admin CLI: python -m app.admin_cli {status|top|errors|refresh|verify ID|unverify ID}
Run via the installed wrapper: sudo vpngate-admin status"""
import datetime
import sys
import time

from app.config import load_config
from app.services import connect, ranking
from app.services.store import Store


def _ts(t):
    return "never" if not t else datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    cfg = load_config()
    store = Store(cfg.db_path)
    now = time.time()
    if cmd == "status":
        s = connect.build_stats(store, cfg, now)
        for k, v in s.items():
            print(f"{k:26} {_ts(v) if k.endswith('_ts') else v}")
        print("last_refresh_summary      ", store.get_meta("last_refresh_rejected") or "{}")
    elif cmd == "top":
        for row, status, score in ranking.rank(store.all_servers(), cfg, now)[:15]:
            v = connect.server_view(row, status, score, now)
            print(f"{v['id']}  {v['country_code']}  {v['transport']}/{v['port']:<5} {status:12} "
                  f"score={score:<6} latency={v['latency_ms']}")
    elif cmd == "errors":
        for e in store.recent_errors(20):
            print(_ts(e["ts"]), e["message"])
    elif cmd == "refresh":
        store.set_meta("refresh_requested", 1)
        print("Refresh requested; the worker picks it up within ~15 seconds.")
    elif cmd in ("verify", "unverify") and len(argv) == 2:
        ok = store.mark_verified(argv[1], cmd == "verify", now)
        print("done" if ok else "unknown server id")
        return 0 if ok else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
