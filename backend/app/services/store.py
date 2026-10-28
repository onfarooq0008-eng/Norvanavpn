"""SQLite persistence (WAL). A new short-lived connection is opened per operation, which keeps the
API (threadpool) and the worker (separate process) safe without shared state."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from app.config import Config
from app.models.records import ServerRecord
from app.security.logging_setup import sanitize

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
  id TEXT PRIMARY KEY, hostname TEXT, ip TEXT, country TEXT, country_code TEXT,
  transport TEXT, port INTEGER, speed_bps INTEGER, ping_ms INTEGER, vpngate_score INTEGER,
  sessions INTEGER, uptime_ms INTEGER, profile TEXT, has_tls_auth INTEGER DEFAULT 0,
  first_seen REAL, last_seen REAL,
  last_check_ts REAL, last_ok_ts REAL, probe_type TEXT, latency_ms REAL,
  probe_ok INTEGER DEFAULT 0, probe_fail INTEGER DEFAULT 0, consec_fail INTEGER DEFAULT 0,
  reliability REAL DEFAULT 0.5, cooldown_until REAL DEFAULT 0, verified_ts REAL,
  client_ok INTEGER DEFAULT 0, client_fail INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS connections (
  id_hash TEXT PRIMARY KEY, server_id TEXT, created REAL, expires REAL, state TEXT
);
CREATE TABLE IF NOT EXISTS events (ts REAL, server_id TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS errors (ts REAL, message TEXT);
"""


def _hash(connection_id: str) -> str:
    return hashlib.sha256(connection_id.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    # ----------------------------------------------------------- meta
    def get_meta(self, key: str) -> Optional[str]:
        with self._conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def get_meta_float(self, key: str) -> Optional[float]:
        v = self.get_meta(key)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    def set_meta(self, key: str, value) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    def log_error(self, message: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self._tx() as c:
            c.execute("INSERT INTO errors(ts,message) VALUES(?,?)", (now, sanitize(message)))
            c.execute("DELETE FROM errors WHERE rowid NOT IN (SELECT rowid FROM errors ORDER BY ts DESC LIMIT 100)")

    def recent_errors(self, limit: int = 10) -> List[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT ts,message FROM errors ORDER BY ts DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------- inventory
    def upsert_inventory(self, records: List[ServerRecord], now: float, rejected_summary: str = "{}") -> None:
        """Atomic: either the whole refresh lands or nothing does. Probe history is preserved."""
        with self._tx() as c:
            for r in records:
                c.execute(
                    """INSERT INTO servers(id,hostname,ip,country,country_code,transport,port,speed_bps,ping_ms,
                       vpngate_score,sessions,uptime_ms,profile,has_tls_auth,first_seen,last_seen)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET hostname=excluded.hostname, country=excluded.country,
                       country_code=excluded.country_code, speed_bps=excluded.speed_bps, ping_ms=excluded.ping_ms,
                       vpngate_score=excluded.vpngate_score, sessions=excluded.sessions,
                       uptime_ms=excluded.uptime_ms, profile=excluded.profile,
                       has_tls_auth=excluded.has_tls_auth, last_seen=excluded.last_seen""",
                    (r.id, r.hostname, r.ip, r.country, r.country_code, r.transport, r.port, r.speed_bps,
                     r.ping_ms, r.vpngate_score, r.sessions, r.uptime_ms, r.profile, int(r.has_tls_auth), now, now))
            c.execute("DELETE FROM servers WHERE last_seen < ?", (now - 7 * 86400,))
            for k, v in (("last_refresh_ok_ts", now), ("last_refresh_count", len(records)),
                         ("last_refresh_rejected", rejected_summary), ("last_refresh_error", "")):
                c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, str(v)))

    def all_servers(self) -> List[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM servers")]

    def get_server(self, sid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    # ----------------------------------------------------------- probes
    def record_probe(self, sid: str, ok: bool, probe_type: str, latency_ms: Optional[float],
                     now: float, cfg: Config) -> None:
        with self._tx() as c:
            r = c.execute("SELECT consec_fail, reliability FROM servers WHERE id=?", (sid,)).fetchone()
            if not r:
                return
            rel = (r["reliability"] if r["reliability"] is not None else 0.5) * 0.7 + (0.3 if ok else 0.0)
            if ok:
                c.execute("""UPDATE servers SET last_check_ts=?, last_ok_ts=?, probe_type=?, latency_ms=?,
                             probe_ok=probe_ok+1, consec_fail=0, reliability=?, cooldown_until=0 WHERE id=?""",
                          (now, now, probe_type, latency_ms, rel, sid))
            else:
                n = (r["consec_fail"] or 0) + 1
                cool = min(cfg.failure_cooldown_s * 2 ** (n - 1), cfg.failure_cooldown_max_s)
                c.execute("""UPDATE servers SET last_check_ts=?, probe_type=?, probe_fail=probe_fail+1,
                             consec_fail=?, reliability=?, cooldown_until=? WHERE id=?""",
                          (now, probe_type, n, rel, now + cool, sid))
                c.execute("INSERT INTO events(ts,server_id,kind) VALUES(?,?,?)", (now, sid, "probe_fail"))

    def mark_verified(self, sid: str, verified: bool, now: float) -> bool:
        with self._tx() as c:
            cur = c.execute("UPDATE servers SET verified_ts=? WHERE id=?", (now if verified else None, sid))
            return cur.rowcount > 0

    # ------------------------------------------------------ connections
    def create_connection(self, connection_id: str, sid: str, now: float, ttl: int) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO connections(id_hash,server_id,created,expires,state) VALUES(?,?,?,?,'issued')",
                      (_hash(connection_id), sid, now, now + ttl))

    def report(self, connection_id: str, sid: str, outcome: str, now: float, cfg: Config) -> str:
        """outcome: success | failure | cancelled | disconnect.
        Returns 'recorded' | 'unknown' | 'already_reported'. Client reports are untrusted signals."""
        h = _hash(connection_id)
        with self._tx() as c:
            row = c.execute("SELECT * FROM connections WHERE id_hash=?", (h,)).fetchone()
            if not row or row["expires"] < now or (sid and row["server_id"] != sid):
                return "unknown"
            state = row["state"]
            if outcome == "disconnect":
                c.execute("DELETE FROM connections WHERE id_hash=?", (h,))
                return "recorded"
            if state != "issued":
                return "already_reported"
            new_state = {"success": "success", "failure": "failed", "cancelled": "cancelled"}[outcome]
            c.execute("UPDATE connections SET state=? WHERE id_hash=?", (new_state, h))
            c.execute("INSERT INTO events(ts,server_id,kind) VALUES(?,?,?)", (now, row["server_id"], "client_" + outcome))
            if outcome == "success":
                c.execute("UPDATE servers SET client_ok=client_ok+1 WHERE id=?", (row["server_id"],))
            elif outcome == "failure":
                s = c.execute("SELECT consec_fail FROM servers WHERE id=?", (row["server_id"],)).fetchone()
                n = ((s["consec_fail"] if s else 0) or 0) + 1
                cool = min(cfg.failure_cooldown_s * 2 ** (n - 1), cfg.failure_cooldown_max_s)
                c.execute("""UPDATE servers SET client_fail=client_fail+1, consec_fail=?, cooldown_until=?
                             WHERE id=?""", (n, now + cool, row["server_id"]))
            return "recorded"

    # ------------------------------------------------------------ stats
    def recent_failures(self, now: float, window_s: float = 86400) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM events WHERE ts>=? AND kind IN ('client_failure','probe_fail')",
                             (now - window_s,)).fetchone()[0]

    def purge(self, now: float, cfg: Config) -> None:
        cutoff = now - cfg.telemetry_retention_days * 86400
        with self._tx() as c:
            c.execute("DELETE FROM events WHERE ts<?", (cutoff,))
            c.execute("DELETE FROM connections WHERE expires<?", (now - 3600,))
            c.execute("DELETE FROM errors WHERE ts<?", (cutoff,))

    def heartbeat(self, now: float) -> None:
        self.set_meta("worker_heartbeat_ts", now)
