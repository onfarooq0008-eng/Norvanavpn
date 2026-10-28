"""Strict allowlist validator for OpenVPN profiles obtained from VPNGate.

All upstream data is untrusted. We parse line by line, accept only directives we
understand, rebuild the profile from validated parts, and never modify security
settings (nothing is added, downgraded or disabled). Anything unknown is rejected.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Optional

from app.config import Config


class ProfileError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ProfileResult:
    text: str
    host: str
    port: int
    transport: str       # "udp" | "tcp"
    has_tls_auth: bool


BLOCK_TAGS = {"ca", "cert", "key", "tls-auth", "tls-crypt", "tls-crypt-v2"}
_BLOCK_LINE = re.compile(r"^[A-Za-z0-9+/=\- ]{1,200}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:+\-]{1,64}$")
_PROTOS = {
    "udp": "udp", "udp4": "udp", "udp6": "udp",
    "tcp": "tcp", "tcp-client": "tcp", "tcp4": "tcp", "tcp4-client": "tcp",
    "tcp6": "tcp", "tcp6-client": "tcp",
}
_WEAK_PREFIXES = ("none", "bf-", "des-", "des3", "rc2", "rc4", "cast", "idea", "seed")
_WEAK_AUTH = {"none", "md4", "md5"}
_REDIRECT_FLAGS = {"def1", "bypass-dhcp", "ipv6"}
_INT_ONE = {"ping", "ping-restart", "reneg-sec", "connect-timeout", "tun-mtu", "sndbuf",
            "rcvbuf", "mute", "hand-window", "tran-window"}
_FLAG_ONLY = {"nobind", "persist-key", "persist-tun", "pull", "tls-client", "auth-nocache"}


def _is_int(s: str, lo: int = 0, hi: int = 10**9) -> bool:
    return s.isdigit() and lo <= int(s) <= hi


def _weak_cipher(name: str) -> bool:
    n = name.lower()
    return any(n.startswith(p) for p in _WEAK_PREFIXES)


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", name.lower())[:24] or "x"


def _norm_proto(p: str) -> str:
    if p not in _PROTOS:
        raise ProfileError("proto_unsupported")
    return _PROTOS[p]


def _directive(name: str, args: list, st: dict, cfg: Config, expected_ip: Optional[str]) -> None:
    n = len(args)
    if name == "client" and n == 0:
        st["client"] = True
    elif name == "dev" and args == ["tun"]:
        st["dev"] = True
    elif name == "dev-type" and args == ["tun"]:
        pass
    elif name == "proto" and n == 1:
        st["proto"] = _norm_proto(args[0])
    elif name == "remote":
        if "host" in st:
            raise ProfileError("multiple_remote")
        if n not in (2, 3) or not _is_int(args[1], 1, 65535):
            raise ProfileError("remote_malformed")
        try:
            ip = ipaddress.ip_address(args[0])
        except ValueError:
            raise ProfileError("remote_host_not_ip") from None
        if ip.version != 4 or not ip.is_global:
            raise ProfileError("remote_not_public_ipv4")
        if expected_ip is not None and args[0] != expected_ip:
            raise ProfileError("remote_mismatch")
        st["host"], st["port"] = args[0], int(args[1])
        if n == 3:
            st["remote_proto"] = _norm_proto(args[2])
    elif name in _FLAG_ONLY and n == 0:
        pass
    elif name == "resolv-retry" and n == 1 and (args[0] == "infinite" or _is_int(args[0])):
        pass
    elif name in ("remote-cert-tls", "ns-cert-type") and args == ["server"]:
        pass
    elif name == "cipher" and n == 1 and _TOKEN.match(args[0]):
        if _weak_cipher(args[0]):
            raise ProfileError("weak_cipher")
    elif name in ("data-ciphers", "data-ciphers-fallback", "ncp-ciphers") and n == 1:
        parts = args[0].split(":")
        if not all(_TOKEN.match(p) for p in parts):
            raise ProfileError("cipher_malformed")
        if any(_weak_cipher(p) for p in parts):
            raise ProfileError("weak_cipher")
    elif name == "auth" and n == 1 and _TOKEN.match(args[0]):
        if args[0].lower() in _WEAK_AUTH:
            raise ProfileError("weak_auth")
    elif name == "keepalive" and n == 2 and all(_is_int(a, 0, 86400) for a in args):
        pass
    elif name in _INT_ONE and n == 1 and _is_int(args[0]):
        pass
    elif name in ("connect-retry", "fragment") and n in (1, 2) and all(_is_int(a) for a in args):
        pass
    elif name == "connect-retry-max" and n == 1 and (args[0] == "unlimited" or _is_int(args[0])):
        pass
    elif name == "mssfix" and n <= 1 and all(_is_int(a) for a in args):
        pass
    elif name == "explicit-exit-notify" and n <= 1 and all(_is_int(a, 0, 10) for a in args):
        pass
    elif name == "verb" and n == 1 and _is_int(args[0], 0, 4):
        pass
    elif name == "tls-version-min" and n in (1, 2) and all(_TOKEN.match(a) for a in args):
        pass
    elif name == "tls-cipher" and n == 1 and re.match(r"^[A-Za-z0-9:_\-]{1,400}$", args[0]):
        pass
    elif name == "key-direction" and n == 1 and args[0] in ("0", "1"):
        pass
    elif name == "redirect-gateway" and all(a in _REDIRECT_FLAGS for a in args):
        pass
    elif name == "verify-x509-name" and n in (1, 2) and _TOKEN.match(args[0]) \
            and (n == 1 or args[1] in ("name", "name-prefix", "subject")):
        pass
    elif name in ("comp-lzo", "compress"):
        if not cfg.allow_compression:
            raise ProfileError("compression_disabled")
        if n > 1 or any(not _TOKEN.match(a) for a in args):
            raise ProfileError("compression_malformed")
    else:
        raise ProfileError("directive:" + _safe_name(name))


def validate_profile(text: str, cfg: Config, expected_ip: Optional[str] = None) -> ProfileResult:
    if not isinstance(text, str):
        raise ProfileError("not_text")
    if len(text.encode("utf-8", "replace")) > cfg.max_profile_bytes:
        raise ProfileError("profile_too_large")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text) or "\x7f" in text:
        raise ProfileError("control_characters")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) > 2000:
        raise ProfileError("too_many_lines")

    st: dict = {}
    out: list = []
    blocks: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line[0] in "#;":
            continue
        if line.startswith("<"):
            m = re.match(r"^<([a-z0-9-]+)>$", line)
            if not m or m.group(1) not in BLOCK_TAGS or m.group(1) in blocks:
                raise ProfileError("block_not_allowed")
            tag = m.group(1)
            body: list = []
            closed = False
            while i < len(lines):
                b = lines[i].strip()
                i += 1
                if b == f"</{tag}>":
                    closed = True
                    break
                if not b:
                    continue
                if not _BLOCK_LINE.match(b):
                    raise ProfileError("block_content_invalid")
                body.append(b)
            if not closed or not body:
                raise ProfileError("block_unterminated")
            joined = "\n".join(body)
            if "-----BEGIN" not in joined or "-----END" not in joined:
                raise ProfileError("block_content_invalid")
            if tag == "ca" and "BEGIN CERTIFICATE" not in joined:
                raise ProfileError("ca_invalid")
            blocks[tag] = f"<{tag}>\n{joined}\n</{tag}>"
            continue
        if any(c in line for c in "\"'\\"):
            raise ProfileError("quote_in_directive")
        parts = line.split()
        _directive(parts[0].lower(), parts[1:], st, cfg, expected_ip)
        out.append(" ".join([parts[0].lower()] + parts[1:]))

    for key, code in (("client", "missing_client"), ("dev", "missing_dev_tun"), ("host", "missing_remote")):
        if key not in st:
            raise ProfileError(code)
    if "ca" not in blocks:
        raise ProfileError("missing_ca")
    proto = st.get("proto")
    rproto = st.get("remote_proto")
    if proto and rproto and proto != rproto:
        raise ProfileError("proto_mismatch")
    transport = proto or rproto or "udp"
    has_auth = "tls-auth" in blocks or "tls-crypt" in blocks or "tls-crypt-v2" in blocks
    final = "\n".join(out + list(blocks.values())) + "\n"
    if len(final.encode()) > cfg.max_profile_bytes:
        raise ProfileError("profile_too_large")
    return ProfileResult(final, st["host"], st["port"], transport, has_auth)
