"""Documented, configurable scoring.

score = 100 * sum(w_i * c_i) / sum(w_i), each component c_i in [0, 1]:
  speed       log1p(advertised Mbps) / log1p(speed_cap_mbps)         (advertised, NOT guaranteed)
  adv_ping    1 - advertised_ping / ping_cap_ms
  latency     1 - measured_latency / latency_cap_ms                  (0 if never measured)
  load        1 - sessions / sessions_cap
  uptime      advertised uptime / uptime_cap_days
  vg_score    log1p(VPNGate score) / log1p(5,000,000)
  reliability EWMA (0.7/0.3) of our own probe outcomes, starts at 0.5
  freshness   0.5 ** (age_of_last_successful_probe / freshness_halflife_s), 0 if none

Status (never inflated):
  candidate     listed + valid profile, no recent successful probe
  reachable     a recent probe succeeded (OpenVPN handshake reply, or TCP connect if tls-auth)
  vpn_verified  an operator marked a real tunnel test as successful (admin action), still fresh
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from app.config import Config

STATUS_RANK = {"vpn_verified": 2, "reachable": 1, "candidate": 0}


def derive_status(row: dict, cfg: Config, now: float) -> str:
    ver = row.get("verified_ts")
    if ver and now - ver <= cfg.verified_ttl_s and (row.get("consec_fail") or 0) == 0:
        return "vpn_verified"
    ok = row.get("last_ok_ts")
    if ok and now - ok <= cfg.reachable_max_age_s and (row.get("consec_fail") or 0) == 0:
        return "reachable"
    return "candidate"


def is_eligible(row: dict, cfg: Config, now: float) -> bool:
    if not row.get("profile"):
        return False
    if now - row["last_seen"] > cfg.server_ttl_s:
        return False
    return (row.get("cooldown_until") or 0) <= now


def components(row: dict, cfg: Config, now: float) -> Dict[str, float]:
    def clamp(x: float) -> float:
        return max(0.0, min(1.0, x))

    mbps = (row.get("speed_bps") or 0) / 1_000_000
    ping = row.get("ping_ms")
    lat = row.get("latency_ms")
    sessions = row.get("sessions")
    up_days = (row.get("uptime_ms") or 0) / 86_400_000
    ok = row.get("last_ok_ts")
    return {
        "speed": clamp(math.log1p(mbps) / math.log1p(cfg.speed_cap_mbps)),
        "adv_ping": clamp(1 - ping / cfg.ping_cap_ms) if ping else 0.0,
        "latency": clamp(1 - lat / cfg.latency_cap_ms) if lat is not None and ok else 0.0,
        "load": clamp(1 - sessions / cfg.sessions_cap) if sessions is not None else 0.5,
        "uptime": clamp(up_days / cfg.uptime_cap_days),
        "vg_score": clamp(math.log1p(row.get("vpngate_score") or 0) / math.log1p(5_000_000)),
        "reliability": clamp(row.get("reliability") if row.get("reliability") is not None else 0.5),
        "freshness": clamp(0.5 ** ((now - ok) / cfg.freshness_halflife_s)) if ok else 0.0,
    }


def compute_score(row: dict, cfg: Config, now: float) -> float:
    comp = components(row, cfg, now)
    total_w = sum(cfg.weights.values())
    return round(100 * sum(cfg.weights.get(k, 0) * v for k, v in comp.items()) / total_w, 2)


def rank(rows: List[dict], cfg: Config, now: float) -> List[Tuple[dict, str, float]]:
    """Eligible rows sorted best-first: status tier, then score."""
    out = []
    for r in rows:
        if is_eligible(r, cfg, now):
            out.append((r, derive_status(r, cfg, now), compute_score(r, cfg, now)))
    out.sort(key=lambda t: (STATUS_RANK[t[1]], t[2]), reverse=True)
    return out


def pick(ranked: List[Tuple[dict, str, float]], cfg: Config, spread: bool,
         rng: Optional[random.Random] = None) -> Optional[Tuple[dict, str, float]]:
    """Best server; with spread=True choose randomly among near-equals of the same tier so a
    single volunteer relay is not hammered by every user."""
    if not ranked:
        return None
    if not spread or cfg.spread_top_n <= 1:
        return ranked[0]
    top = ranked[0]
    pool = [t for t in ranked[: cfg.spread_top_n]
            if STATUS_RANK[t[1]] == STATUS_RANK[top[1]] and top[2] - t[2] <= cfg.spread_score_window]
    return (rng or random).choice(pool)
