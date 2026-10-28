from __future__ import annotations

import logging
import re
import sys
from typing import Iterable

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.S)
_B64_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{120,}")


def sanitize(text: str, secrets: Iterable[str] = ()) -> str:
    out = _PEM.sub("[pem-redacted]", str(text))
    out = _B64_BLOB.sub("[blob-redacted]", out)
    for s in secrets:
        if s:
            out = out.replace(s, "[secret-redacted]")
    return out[:500]


class SanitizingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(record.getMessage(), self._secrets)
        record.args = ()
        return True


def setup_logging(secrets: Iterable[str] = (), level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)  # journald captures stdout
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SanitizingFilter(secrets))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
