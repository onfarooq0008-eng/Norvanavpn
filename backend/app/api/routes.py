from __future__ import annotations

import html
import time
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.errors import ApiError
from app.config import Config
from app.models.schemas import (ConnectRequest, DisconnectRequest, ReportRequest, SuccessRequest,
                                VerifyRequest)
from app.security import auth
from app.security.ratelimit import RateLimiter
from app.services import connect, ranking
from app.services.store import Store


class Ctx:
    def __init__(self, cfg: Config, store: Store, limiter: RateLimiter, clock=time.time):
        self.cfg, self.store, self.limiter, self.clock = cfg, store, limiter, clock
        self.started = clock()


def client_key(request: Request, cfg: Config) -> str:
    if cfg.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def build_router(ctx: Ctx) -> APIRouter:
    r = APIRouter()
    cfg, store = ctx.cfg, ctx.store

    def limit(request: Request, bucket: str, per_min: int) -> None:
        ok, retry = ctx.limiter.check(bucket, client_key(request, cfg), per_min)
        if not ok:
            raise ApiError(429, "rate_limited", "Too many requests.", {"Retry-After": str(int(retry) + 1)})

    def app_gate(request: Request, bucket: str, per_min: int, key: Optional[str]) -> None:
        limit(request, bucket, per_min)
        if not auth.check_app_key(key, cfg.app_api_key):
            raise ApiError(401, "unauthorized", "Missing or invalid API key.")

    def admin_gate(request: Request) -> None:
        limit(request, "admin", cfg.rate_limit_admin_per_min)
        if not auth.check_admin(request.headers.get("authorization"), cfg.admin_secret):
            raise ApiError(401, "unauthorized", "Authentication required.", {"WWW-Authenticate": 'Basic realm="admin"'})

    def sid_or_400(server_id: str) -> str:
        if not auth.valid_server_id(server_id):
            raise ApiError(400, "invalid_server_id", "Invalid server id.")
        return server_id

    def svc(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except connect.ServiceError as e:
            raise ApiError(e.status, e.code, e.message)

    # ------------------------------------------------------------ health
    @r.get("/health")
    def health():
        now = ctx.clock()
        st = connect.build_stats(store, cfg, now)
        if st["last_refresh_ok_ts"] is None:
            status = "starting"
        elif st["inventory_stale"] or st["eligible"] == 0 or (
                st["worker_heartbeat_age_s"] is None or st["worker_heartbeat_age_s"] > 120):
            status = "degraded"
        else:
            status = "ok"
        return {"status": status, "api_uptime_s": round(now - ctx.started),
                "last_refresh_ok": None if st["last_refresh_ok_ts"] is None else connect._iso(st["last_refresh_ok_ts"]),
                "cache_age_s": st["cache_age_s"], "eligible_servers": st["eligible"],
                "worker_heartbeat_age_s": st["worker_heartbeat_age_s"]}

    # ----------------------------------------------------------- servers
    @r.get("/api/v1/servers")
    def list_servers(request: Request, country: Optional[str] = Query(None, pattern=r"^[A-Za-z]{2}$"),
                     protocol: Optional[str] = Query(None, pattern=r"^(udp|tcp)$"),
                     min_quality: float = Query(0, ge=0, le=100),
                     limit_: int = Query(20, alias="limit", ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                     x_api_key: Optional[str] = Header(None)):
        app_gate(request, "read", cfg.rate_limit_read_per_min, x_api_key)
        now = ctx.clock()
        ranked = connect.eligible_ranked(store, cfg, now, protocol=protocol, country=country, min_quality=min_quality)
        page = ranked[offset: offset + limit_]
        return {"success": True, "total": len(ranked), "limit": limit_, "offset": offset,
                "servers": [connect.server_view(row, st, sc, now) for row, st, sc in page]}

    @r.get("/api/v1/servers/fastest")
    def fastest(request: Request, country: Optional[str] = Query(None, pattern=r"^[A-Za-z]{2}$"),
                protocol: Optional[str] = Query(None, pattern=r"^(udp|tcp)$"),
                min_quality: float = Query(0, ge=0, le=100), x_api_key: Optional[str] = Header(None)):
        app_gate(request, "read", cfg.rate_limit_read_per_min, x_api_key)
        now = ctx.clock()
        row, st, sc = svc(connect.select_server, store, cfg, now, spread=False, protocol=protocol,
                          country=country, min_quality=min_quality)
        return {"success": True, "server": connect.server_view(row, st, sc, now)}

    # ----------------------------------------------------------- connect
    @r.post("/api/v1/connect")
    def do_connect(request: Request, body: Optional[ConnectRequest] = None, x_api_key: Optional[str] = Header(None)):
        app_gate(request, "connect", cfg.rate_limit_connect_per_min, x_api_key)
        b = body or ConnectRequest()
        for s in b.exclude:
            sid_or_400(s)
        return svc(connect.issue_connection, store, cfg, ctx.clock(), protocol=b.protocol, country=b.country,
                   exclude=b.exclude, min_quality=b.min_quality)

    @r.post("/api/v1/servers/{server_id}/failure")
    def failure(server_id: str, body: ReportRequest, request: Request, x_api_key: Optional[str] = Header(None)):
        app_gate(request, "report", cfg.rate_limit_report_per_min, x_api_key)
        sid_or_400(server_id)
        outcome = "cancelled" if body.reason == "cancelled" else "failure"
        svc(connect.record_report, store, cfg, ctx.clock(), server_id, body.connection_id, outcome)
        return {"success": True, "recorded": True}

    @r.post("/api/v1/servers/{server_id}/success")
    def success(server_id: str, body: SuccessRequest, request: Request, x_api_key: Optional[str] = Header(None)):
        app_gate(request, "report", cfg.rate_limit_report_per_min, x_api_key)
        sid_or_400(server_id)
        svc(connect.record_report, store, cfg, ctx.clock(), server_id, body.connection_id, "success")
        return {"success": True, "recorded": True}

    @r.post("/api/v1/disconnect")
    def disconnect(body: DisconnectRequest, request: Request, x_api_key: Optional[str] = Header(None)):
        app_gate(request, "report", cfg.rate_limit_report_per_min, x_api_key)
        store.report(body.connection_id, "", "disconnect", ctx.clock(), cfg)  # idempotent; no existence oracle
        return {"success": True}

    @r.get("/api/v1/stats")
    def stats(request: Request, x_api_key: Optional[str] = Header(None)):
        app_gate(request, "read", cfg.rate_limit_read_per_min, x_api_key)
        s = connect.build_stats(store, cfg, ctx.clock())
        s.pop("last_refresh_error", None)
        return {"success": True, "stats": s}

    # ------------------------------------------------------------- admin
    @r.get("/admin/api/status")
    def admin_status(request: Request):
        admin_gate(request)
        now = ctx.clock()
        return {"success": True, "stats": connect.build_stats(store, cfg, now),
                "api_uptime_s": round(now - ctx.started),
                "errors": [{"ts": e["ts"], "message": e["message"]} for e in store.recent_errors(10)]}

    @r.get("/admin/", response_class=HTMLResponse)
    def admin_page(request: Request):
        admin_gate(request)
        now = ctx.clock()
        s = connect.build_stats(store, cfg, now)
        esc = lambda v: html.escape(str(v))  # noqa: E731
        top = ranking.rank(store.all_servers(), cfg, now)[:10]
        rows = "".join(
            f"<tr><td>{esc(v['id'])}</td><td>{esc(v['country_code'])}</td><td>{esc(v['transport'])}/{esc(v['port'])}</td>"
            f"<td>{esc(v['verification_status'])}</td><td>{esc(v['quality_score'])}</td><td>{esc(v['latency_ms'])}</td></tr>"
            for v in (connect.server_view(rw, st, sc, now) for rw, st, sc in top))
        errs = "".join(f"<li>{esc(e['message'])}</li>" for e in store.recent_errors(10))
        stat_rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in s.items())
        page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                f"<title>VPNGate backend</title><style>body{{font:14px sans-serif;margin:1rem}}"
                f"td,th{{border:1px solid #ccc;padding:3px 8px;text-align:left}}</style>"
                f"<h1>VPNGate backend</h1><p>API uptime: {esc(round(now - ctx.started))} s</p>"
                f"<table>{stat_rows}</table><h2>Top servers</h2><table><tr><th>id</th><th>cc</th><th>port</th>"
                f"<th>status</th><th>score</th><th>latency ms</th></tr>{rows}</table>"
                f"<h2>Recent errors</h2><ul>{errs or '<li>none</li>'}</ul>")
        return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @r.post("/admin/refresh")
    def admin_refresh(request: Request):
        admin_gate(request)
        store.set_meta("refresh_requested", 1)
        return {"success": True, "message": "Refresh requested."}

    @r.post("/admin/servers/{server_id}/verified")
    def admin_verified(server_id: str, body: VerifyRequest, request: Request):
        admin_gate(request)
        sid_or_400(server_id)
        if not store.mark_verified(server_id, body.verified, ctx.clock()):
            raise ApiError(404, "unknown_server", "Unknown server.")
        return {"success": True}

    return r
