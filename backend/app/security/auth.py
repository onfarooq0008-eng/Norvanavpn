from __future__ import annotations

import base64
import binascii
import hmac
import re
from typing import Optional, Tuple

SERVER_ID_RE = re.compile(r"^[a-f0-9]{16}$")
CONNECTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def valid_server_id(value: str) -> bool:
    return bool(SERVER_ID_RE.match(value or ""))


def valid_connection_id(value: str) -> bool:
    return bool(CONNECTION_ID_RE.match(value or ""))


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def parse_basic_auth(header: Optional[str]) -> Optional[Tuple[str, str]]:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    user, sep, pw = raw.partition(":")
    return (user, pw) if sep else None


def check_admin(header: Optional[str], admin_secret: str) -> bool:
    """Admin auth = HTTP Basic, username 'admin', password = admin secret.
    Always False when no secret is configured (admin disabled)."""
    if not admin_secret:
        return False
    creds = parse_basic_auth(header)
    if creds is None:
        return False
    user_ok = constant_time_equal(creds[0], "admin")
    pw_ok = constant_time_equal(creds[1], admin_secret)
    return user_ok and pw_ok


def check_app_key(provided: Optional[str], app_key: str) -> bool:
    """Skipped when no app key is configured. A key shipped in an APK is extractable;
    it only raises the bar against casual abuse."""
    if not app_key:
        return True
    return bool(provided) and constant_time_equal(provided, app_key)
