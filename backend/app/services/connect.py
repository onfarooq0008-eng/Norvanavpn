"""Business logic shared by the REST layer and tests (no web framework imports)."""
from __future__ import annotations

import random
import secrets
from typing import Dict, Iterable, List, Optional

from app.config import Config
from app.services import ranking
from app.services.store import Store

NOTICE = ("Public VPNGate relays are run by volunteers. Operators may be able to observe connection "
          "metadata and any traffic that is not itself encrypted (use HTTPS). Do not rely on this for anonymity.")


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def inventory_state(store: Store, cfg: Config, now: float) -> Dict:
    last = store.get_meta_float("last_refresh_ok_ts")
    age = None if last is None else max(0.0, now - last)
    return {"last_refresh_ok_ts": last, "cache_age_s": age,
            "stale": age is not None and age > cfg.inventory_stale_after_s,
            "expired": age is None or age > cfg.inventory_max_age_s}


def server_view(row: dict, status: str, score: float, now: float) -> Dict:
    return {
        "id": row["id"], "hostname": row["hostname"], "ip": row["ip"],
        "country": row["country"], "country_code": row["country_code"],
        "protocol": "openvpn", "transport": row["transport"], "port": row["port"],
        "verification_status": status,
        "probe_type": row.get("probe_type") if status != "candidate" else None,
        "latency_ms": None if row.get("latency_ms") is None or status == "candidate" else round(row["latency_ms"], 1),
        "quality_score": score,
        "advertised_speed_mbps": round((row.get("speed_bps") or 0) / 1_000_000, 2),
        "advertised_ping_ms": row.get("ping_ms"),
        "sessions": row.get("sessions"),
        "last_checked_age_s": None if not row.get("last_check_ts") else round(now - row["last_check_ts"]),
    }


def eligible_ranked(store: Store, cfg: Config, now: float, protocol: Optional[str] = None,
                    country: Optional[str] = None, exclude: Iterable[str] = (),
                    min_quality: float = 0.0) -> List:
    excl = set(exclude)
    rows = [r for r in store.all_servers()
            if r["id"] not in excl
            and (not protocol or protocol == "any" or r["transport"] == protocol)
            and (not country or r["country_code"] == country.upper())]
    return [t for t in ranking.rank(rows, cfg, now) if t[2] >= min_quality]


def select_server(store: Store, cfg: Config, now: float, *, spread: bool, rng: Optional[random.Random] = None,
                  **filters):
    state = inventory_state(store, cfg, now)
    if state["expired"]:
        raise ServiceError(503, "inventory_unavailable", "Server inventory is not available right now. Try again later.")
    picked = ranking.pick(eligible_ranked(store, cfg, now, **filters), cfg, spread, rng)
    if picked is None:
        raise ServiceError(503, "no_server_available", "No eligible server matches the request. Try again later.")
    return picked


def issue_connection(store: Store, cfg: Config, now: float, rng: Optional[random.Random] = None, **filters) -> Dict:
    row, status, score = select_server(store, cfg, now, spread=True, rng=rng, **filters)
    connection_id = secrets.token_urlsafe(24)
    store.create_connection(connection_id, row["id"], now, cfg.connection_ttl_s)
    return {
        "success": True,
        "connection_id": connection_id,
        "server": server_view(row, status, score, now),
        "openvpn_profile": row["profile"],
        "expires_at": _iso(now + cfg.connection_ttl_s),
        "notice": NOTICE,
    }


def record_report(store: Store, cfg: Config, now: float, server_id: str, connection_id: str, outcome: str) -> None:
    result = store.report(connection_id, server_id, outcome, now, cfg)
    if result == "unknown":
        raise ServiceError(404, "unknown_connection", "Unknown or expired connection.")
    if result == "already_reported":
        raise ServiceError(409, "already_reported", "This connection already has a report.")


def build_stats(store: Store, cfg: Config, now: float) -> Dict:
    rows = store.all_servers()
    fresh = [r for r in rows if now - r["last_seen"] <= cfg.server_ttl_s]
    statuses = [ranking.derive_status(r, cfg, now) for r in fresh]
    st = inventory_state(store, cfg, now)
    hb = store.get_meta_float("worker_heartbeat_ts")
    return {
        "candidates": len(fresh),
        "reachable": statuses.count("reachable"),
        "vpn_verified": statuses.count("vpn_verified"),
        "eligible": len(ranking.rank(fresh, cfg, now)),
        "in_cooldown": sum(1 for r in fresh if (r.get("cooldown_until") or 0) > now),
        "recent_failures_24h": store.recent_failures(now),
        "last_refresh_ok_ts": st["last_refresh_ok_ts"],
        "cache_age_s": None if st["cache_age_s"] is None else round(st["cache_age_s"]),
        "inventory_stale": st["stale"],
        "last_refresh_error": store.get_meta("last_refresh_error") or None,
        "worker_heartbeat_age_s": None if hb is None else round(now - hb),
    }


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
