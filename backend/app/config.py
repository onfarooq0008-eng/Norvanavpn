"""Configuration loading and validation.

Non-secret settings come from a JSON file (default /etc/vpngate-backend/config.json).
Secrets (admin secret, optional app API key) come ONLY from environment variables,
which systemd loads from a root-only env file.
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

DEFAULT_CONFIG_PATH = "/etc/vpngate-backend/config.json"

DEFAULT_WEIGHTS = {
    "speed": 0.20,        # advertised throughput (log-scaled, capped)
    "adv_ping": 0.05,     # VPNGate-advertised ping
    "latency": 0.20,      # latency measured from THIS backend
    "load": 0.10,         # advertised session count (lower is better)
    "uptime": 0.05,       # advertised uptime
    "vg_score": 0.05,     # VPNGate's own score (log-scaled)
    "reliability": 0.20,  # EWMA of our probe results
    "freshness": 0.15,    # how recently a probe succeeded
}


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    # --- upstream -----------------------------------------------------
    upstream_url: str = "https://www.vpngate.net/api/iphone/"
    allowed_upstream_hosts: list = field(default_factory=lambda: ["www.vpngate.net"])
    allow_insecure_upstream: bool = False
    max_response_bytes: int = 10_000_000
    http_timeout_s: float = 20.0
    fetch_retries: int = 3
    fetch_backoff_base_s: float = 2.0
    user_agent: str = "vpngate-backend/1.0 (self-hosted; polite client)"
    # --- refresh / probing -------------------------------------------
    refresh_interval_s: int = 1800
    refresh_failure_wait_s: int = 600
    probe_enabled: bool = True
    probe_round_interval_s: int = 300
    probe_concurrency: int = 4
    probe_timeout_s: float = 4.0
    probe_top_n: int = 40
    probe_max_per_round: int = 20
    probe_recheck_s: int = 900
    # --- eligibility / cooldowns --------------------------------------
    server_ttl_s: int = 21600
    inventory_stale_after_s: int = 10800
    inventory_max_age_s: int = 43200
    failure_cooldown_s: int = 600
    failure_cooldown_max_s: int = 21600
    reachable_max_age_s: int = 3600
    verified_ttl_s: int = 604800
    # --- ranking ------------------------------------------------------
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    speed_cap_mbps: float = 100.0
    ping_cap_ms: float = 300.0
    latency_cap_ms: float = 400.0
    sessions_cap: float = 200.0
    uptime_cap_days: float = 30.0
    freshness_halflife_s: float = 1800.0
    spread_top_n: int = 3
    spread_score_window: float = 8.0
    # --- profile validation ------------------------------------------
    max_profile_bytes: int = 49152
    allow_compression: bool = False
    # --- API ----------------------------------------------------------
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    allow_public_bind: bool = False
    trust_proxy_headers: bool = True
    enable_docs: bool = False
    max_request_bytes: int = 8192
    connection_ttl_s: int = 600
    rate_limit_connect_per_min: int = 10
    rate_limit_report_per_min: int = 30
    rate_limit_read_per_min: int = 60
    rate_limit_admin_per_min: int = 10
    telemetry_retention_days: int = 7
    # --- storage / secrets (secrets come from env only) ----------------
    db_path: str = "/var/lib/vpngate-backend/vpngate.db"
    admin_secret: str = ""
    app_api_key: str = ""

    def validate(self) -> "Config":
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ConfigError(msg)

        u = urlparse(self.upstream_url)
        need(u.scheme in ("https", "http") and bool(u.hostname), "upstream_url must be an http(s) URL")
        need(u.scheme == "https" or self.allow_insecure_upstream,
             "upstream_url must be https (set allow_insecure_upstream=true only if you accept the risk)")
        need(u.hostname in self.allowed_upstream_hosts, "upstream_url host is not in allowed_upstream_hosts")
        need(self.refresh_interval_s >= 600, "refresh_interval_s must be >= 600 (be polite to volunteer servers)")
        need(self.refresh_failure_wait_s >= 300, "refresh_failure_wait_s must be >= 300")
        need(1 <= self.probe_concurrency <= 20, "probe_concurrency must be 1..20")
        need(1.0 <= self.probe_timeout_s <= 15.0, "probe_timeout_s must be 1..15")
        need(1 <= self.probe_max_per_round <= 100, "probe_max_per_round must be 1..100")
        need(self.probe_round_interval_s >= 60, "probe_round_interval_s must be >= 60")
        need(self.probe_recheck_s >= 300, "probe_recheck_s must be >= 300")
        need(self.failure_cooldown_s >= 60, "failure_cooldown_s must be >= 60")
        need(self.failure_cooldown_max_s >= self.failure_cooldown_s, "failure_cooldown_max_s too small")
        need(0 <= self.fetch_retries <= 6, "fetch_retries must be 0..6")
        need(1_000 <= self.max_profile_bytes <= 262_144, "max_profile_bytes must be 1000..262144")
        need(1_000_000 <= self.max_response_bytes <= 50_000_000, "max_response_bytes must be 1MB..50MB")
        need(30 <= self.connection_ttl_s <= 3600, "connection_ttl_s must be 30..3600")
        need(512 <= self.max_request_bytes <= 65536, "max_request_bytes must be 512..65536")
        need(set(self.weights) <= set(DEFAULT_WEIGHTS), "unknown weight name")
        need(all(isinstance(v, (int, float)) and v >= 0 for v in self.weights.values())
             and sum(self.weights.values()) > 0, "weights must be non-negative with a positive sum")
        need(1 <= self.bind_port <= 65535, "bind_port out of range")
        need(self.allow_public_bind or self.bind_host in ("127.0.0.1", "::1", "localhost"),
             "bind_host must be loopback unless allow_public_bind=true (use nginx + HTTPS for public access)")
        for name in ("rate_limit_connect_per_min", "rate_limit_report_per_min",
                     "rate_limit_read_per_min", "rate_limit_admin_per_min"):
            need(getattr(self, name) >= 1, f"{name} must be >= 1")
        need(1 <= self.telemetry_retention_days <= 365, "telemetry_retention_days must be 1..365")
        need(self.admin_secret == "" or len(self.admin_secret) >= 24, "admin secret must be at least 24 characters")
        return self


def load_config(path: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if env is None else env
    explicit = path or env.get("VPNGATE_CONFIG")
    cfg_path = explicit or DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read config file: {type(exc).__name__}") from None
        if not isinstance(data, dict):
            raise ConfigError("config file must contain a JSON object")
    elif explicit:
        raise ConfigError("config file not found")
    known = {f.name for f in dataclasses.fields(Config)} - {"admin_secret", "app_api_key"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError("unknown config keys: " + ", ".join(sorted(unknown)))
    cfg = Config(**data)
    if "weights" in data:
        merged = dict(DEFAULT_WEIGHTS)
        merged.update(data["weights"])
        cfg.weights = merged
    if env.get("VPNGATE_DB_PATH"):
        cfg.db_path = env["VPNGATE_DB_PATH"]
    cfg.admin_secret = env.get("VPNGATE_ADMIN_SECRET", "")
    cfg.app_api_key = env.get("VPNGATE_APP_API_KEY", "")
    return cfg.validate()
