from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ServerRecord:
    id: str
    hostname: str
    ip: str
    country: str
    country_code: str
    transport: str          # "udp" | "tcp"
    port: int
    speed_bps: Optional[int]
    ping_ms: Optional[int]
    vpngate_score: Optional[int]
    sessions: Optional[int]
    uptime_ms: Optional[int]
    profile: str            # validated, sanitised OpenVPN profile
    has_tls_auth: bool      # tls-auth/tls-crypt present -> cannot craft a handshake probe


@dataclass
class ProbeResult:
    ok: bool
    latency_ms: Optional[float]
    probe_type: str         # "openvpn_reset" | "tcp_connect" | "none"
