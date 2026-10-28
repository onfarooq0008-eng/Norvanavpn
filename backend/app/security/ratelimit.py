from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Tuple


class RateLimiter:
    """In-memory sliding-window limiter. Keys (client addresses) live only in RAM,
    are never logged or persisted, and the table is size-bounded."""

    def __init__(self, max_keys: int = 20000, clock: Callable[[], float] = time.monotonic):
        self._hits: "OrderedDict[Tuple[str, str], Deque[float]]" = OrderedDict()
        self._max_keys = max_keys
        self._clock = clock

    def check(self, bucket: str, key: str, limit: int, window_s: float = 60.0) -> Tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = self._clock()
        k = (bucket, key)
        dq = self._hits.get(k)
        if dq is None:
            dq = deque()
            self._hits[k] = dq
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(k)
        cutoff = now - window_s
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False, max(0.0, dq[0] + window_s - now)
        dq.append(now)
        return True, 0.0
