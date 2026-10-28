"""Background refresh + probe scheduler (runs in its own process: app.worker)."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Awaitable, Callable, Optional

from app.config import Config
from app.models.records import ProbeResult
from app.services import ranking, vpngate
from app.services.probe import probe_server
from app.services.store import Store

log = logging.getLogger("vpngate.worker")


class RefreshWorker:
    def __init__(self, cfg: Config, store: Store,
                 fetcher: Optional[Callable[[], Awaitable[str]]] = None,
                 prober: Optional[Callable[[dict], Awaitable[Optional[ProbeResult]]]] = None,
                 clock: Callable[[], float] = time.time,
                 rng: Optional[random.Random] = None):
        self.cfg, self.store, self.clock = cfg, store, clock
        self.fetcher = fetcher or (lambda: vpngate.fetch_list(cfg))
        self.prober = prober or (lambda row: probe_server(row, cfg.probe_timeout_s))
        self.rng = rng or random.Random()
        self._refresh_lock = asyncio.Lock()
        self._probe_lock = asyncio.Lock()

    async def run_refresh(self) -> bool:
        """Returns True on success. Never overlaps; keeps last known-good inventory on any failure."""
        if self._refresh_lock.locked():
            return False
        async with self._refresh_lock:
            now = self.clock()
            self.store.set_meta("last_refresh_attempt_ts", now)
            try:
                text = await self.fetcher()
                parsed = vpngate.parse_csv(text, self.cfg)
                if not parsed.servers:
                    raise vpngate.FetchError("upstream list contained no valid OpenVPN servers")
            except (vpngate.FetchError, Exception) as exc:  # noqa: BLE001 - worker must not die
                msg = f"refresh failed: {type(exc).__name__}: {exc}"
                log.warning(msg)
                self.store.set_meta("last_refresh_error", msg[:300])
                self.store.set_meta("last_refresh_attempt_ok", 0)
                self.store.log_error(msg, now)
                return False
            summary = {"rows": parsed.total_rows, "accepted": len(parsed.servers),
                       "duplicates": parsed.duplicates, "rejected": parsed.rejected}
            self.store.upsert_inventory(parsed.servers, now, json.dumps(summary))
            self.store.set_meta("last_refresh_attempt_ok", 1)
            log.info("refresh ok: %d servers accepted of %d rows", len(parsed.servers), parsed.total_rows)
            return True

    async def run_probes(self) -> int:
        if not self.cfg.probe_enabled or self._probe_lock.locked():
            return 0
        async with self._probe_lock:
            now = self.clock()
            self.store.set_meta("last_probe_round_ts", now)
            rows = [r for r in self.store.all_servers()
                    if now - r["last_seen"] <= self.cfg.server_ttl_s and r.get("profile")
                    and (r.get("cooldown_until") or 0) <= now]
            rows.sort(key=lambda r: ranking.compute_score(r, self.cfg, now), reverse=True)
            rows = rows[: self.cfg.probe_top_n]
            due = [r for r in rows if not r.get("last_check_ts") or now - r["last_check_ts"] >= self.cfg.probe_recheck_s]
            due.sort(key=lambda r: r.get("last_check_ts") or 0)
            due = due[: self.cfg.probe_max_per_round]
            sem = asyncio.Semaphore(self.cfg.probe_concurrency)
            done = 0

            async def one(row: dict) -> None:
                nonlocal done
                async with sem:
                    await asyncio.sleep(self.rng.uniform(0, 0.5))
                    try:
                        res = await self.prober(row)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("probe error: %s", type(exc).__name__)
                        return
                    if res is None:
                        return
                    self.store.record_probe(row["id"], res.ok, res.probe_type, res.latency_ms, self.clock(), self.cfg)
                    done += 1

            await asyncio.gather(*(one(r) for r in due))
            return done

    def refresh_due(self, now: float) -> bool:
        if self.store.get_meta("refresh_requested") == "1":
            return True
        attempt = self.store.get_meta_float("last_refresh_attempt_ts")
        if attempt is None:
            return True
        ok = self.store.get_meta("last_refresh_attempt_ok") == "1"
        wait = self.cfg.refresh_interval_s if ok else self.cfg.refresh_failure_wait_s
        return now - attempt >= wait

    def probes_due(self, now: float) -> bool:
        last = self.store.get_meta_float("last_probe_round_ts")
        return last is None or now - last >= self.cfg.probe_round_interval_s

    async def tick(self) -> None:
        now = self.clock()
        self.store.heartbeat(now)
        if self.refresh_due(now):
            self.store.set_meta("refresh_requested", 0)
            await self.run_refresh()
        if self.probes_due(self.clock()):
            await self.run_probes()
        last_purge = self.store.get_meta_float("last_purge_ts")
        if last_purge is None or now - last_purge > 3600:
            self.store.purge(now, self.cfg)
            self.store.set_meta("last_purge_ts", now)

    async def loop(self, tick_s: float = 15.0) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("tick failed: %s", type(exc).__name__)
            await asyncio.sleep(tick_s)
