"""VPNGate list download (documented CSV 'iphone' API) and parsing.

The endpoint is configurable (config.upstream_url). Default: https://www.vpngate.net/api/iphone/
Format: first line '*vpn_servers', second line '#HostName,IP,Score,...', CSV rows, last line '*'.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import hashlib
import io
import ipaddress
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from app.config import Config
from app.models.records import ServerRecord
from app.services.profile import ProfileError, validate_profile


class FetchError(Exception):
    pass


class UpstreamFormatError(FetchError):
    pass


@dataclass
class ParseResult:
    servers: List[ServerRecord] = field(default_factory=list)
    rejected: Dict[str, int] = field(default_factory=dict)
    total_rows: int = 0
    duplicates: int = 0


def server_id(ip: str, transport: str, port: int) -> str:
    return hashlib.sha256(f"{ip}|{transport}|{port}".encode()).hexdigest()[:16]


def _int(s: Optional[str]) -> Optional[int]:
    s = (s or "").strip()
    if s.isdigit() and len(s) <= 15:
        return int(s)
    return None


_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _clean_text(s: str, limit: int = 64) -> str:
    return "".join(c for c in (s or "") if c.isprintable())[:limit].strip()


def parse_csv(text: str, cfg: Config) -> ParseResult:
    text = text.lstrip("\ufeff")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "*vpn_servers":
        raise UpstreamFormatError("missing '*vpn_servers' marker")
    if len(lines) < 2 or not lines[1].startswith("#"):
        raise UpstreamFormatError("missing CSV header")
    header = [h.strip() for h in next(csv.reader([lines[1][1:]]))]
    col = {name: idx for idx, name in enumerate(header)}
    for needed in ("HostName", "IP", "CountryShort", "OpenVPN_ConfigData_Base64"):
        if needed not in col:
            raise UpstreamFormatError("CSV header lacks required column")

    rejected: Counter = Counter()
    best: Dict[str, ServerRecord] = {}
    total = 0
    duplicates = 0
    for row in csv.reader(l for l in lines[2:] if l.strip() != "*"):
        total += 1
        if len(row) != len(header):
            rejected["malformed_row"] += 1
            continue
        ip = row[col["IP"]].strip()
        try:
            ipobj = ipaddress.ip_address(ip)
            if ipobj.version != 4 or not ipobj.is_global:
                raise ValueError
        except ValueError:
            rejected["invalid_ip"] += 1
            continue
        b64 = row[col["OpenVPN_ConfigData_Base64"]].strip()
        if not b64:
            rejected["no_openvpn_config"] += 1
            continue
        if len(b64) > cfg.max_profile_bytes * 2:
            rejected["profile_too_large"] += 1
            continue
        try:
            raw = base64.b64decode(b64, validate=True)
            profile_text = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            rejected["profile_decode_error"] += 1
            continue
        try:
            prof = validate_profile(profile_text, cfg, expected_ip=ip)
        except ProfileError as exc:
            rejected["profile:" + exc.code] += 1
            continue
        host = row[col["HostName"]].strip()
        if not _HOST_RE.match(host):
            host = ip
        cc = row[col["CountryShort"]].strip().upper()
        cc = cc if re.fullmatch(r"[A-Z]{2}", cc) else "XX"
        country = _clean_text(row[col["CountryLong"]]) if "CountryLong" in col else ""
        get = lambda name: _int(row[col[name]]) if name in col else None  # noqa: E731
        rec = ServerRecord(
            id=server_id(ip, prof.transport, prof.port), hostname=host, ip=ip,
            country=country or cc, country_code=cc, transport=prof.transport, port=prof.port,
            speed_bps=get("Speed"), ping_ms=get("Ping"), vpngate_score=get("Score"),
            sessions=get("NumVpnSessions"), uptime_ms=get("Uptime"),
            profile=prof.text, has_tls_auth=prof.has_tls_auth,
        )
        prev = best.get(rec.id)
        if prev is not None:
            duplicates += 1
            if (rec.vpngate_score or 0) <= (prev.vpngate_score or 0):
                continue
        best[rec.id] = rec
    return ParseResult(list(best.values()), dict(rejected), total, duplicates)


# ---------------------------------------------------------------- fetching
def check_upstream_url(cfg: Config) -> None:
    u = urlparse(cfg.upstream_url)
    if u.hostname not in cfg.allowed_upstream_hosts:
        raise FetchError("upstream host not allowed")
    if u.scheme != "https" and not cfg.allow_insecure_upstream:
        raise FetchError("insecure upstream not allowed")


async def fetch_with_retries(fetch_once: Callable[[], Awaitable[str]], cfg: Config,
                             sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                             rng: Optional[random.Random] = None) -> str:
    rng = rng or random.Random()
    last: Optional[Exception] = None
    for attempt in range(cfg.fetch_retries + 1):
        try:
            return await fetch_once()
        except UpstreamFormatError:
            raise
        except FetchError as exc:
            last = exc
        if attempt < cfg.fetch_retries:
            await sleep(cfg.fetch_backoff_base_s * (2 ** attempt) + rng.uniform(0, 1))
    raise FetchError(f"upstream unavailable after {cfg.fetch_retries + 1} attempts: {last}")


async def fetch_list(cfg: Config) -> str:
    """Download the CSV with timeouts, size cap, no redirects, retries and backoff."""
    import httpx  # imported lazily so parsing/tests do not require it

    check_upstream_url(cfg)

    async def once() -> str:
        timeout = httpx.Timeout(cfg.http_timeout_s, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                         headers={"User-Agent": cfg.user_agent}) as client:
                async with client.stream("GET", cfg.upstream_url) as resp:
                    if resp.status_code != 200:
                        raise FetchError(f"upstream HTTP {resp.status_code}")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf += chunk
                        if len(buf) > cfg.max_response_bytes:
                            raise FetchError("upstream response too large")
        except httpx.HTTPError as exc:
            raise FetchError(f"network error: {type(exc).__name__}") from None
        try:
            text = bytes(buf).decode("utf-8")
        except UnicodeDecodeError:
            raise UpstreamFormatError("response is not UTF-8") from None
        if not text.lstrip("\ufeff").lstrip().startswith("*vpn_servers"):
            raise UpstreamFormatError("unexpected content")
        return text

    return await fetch_with_retries(once, cfg)
