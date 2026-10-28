"""FastAPI application factory. Run with:  uvicorn app.main:create_app --factory"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import ApiError, error_body
from app.api.routes import Ctx, build_router
from app.config import Config, load_config
from app.security.logging_setup import setup_logging
from app.security.ratelimit import RateLimiter
from app.services.store import Store

log = logging.getLogger("vpngate.api")


def create_app(cfg: Optional[Config] = None, store: Optional[Store] = None, clock=None) -> FastAPI:
    if cfg is None:
        cfg = load_config()
        setup_logging([cfg.admin_secret, cfg.app_api_key])
    store = store or Store(cfg.db_path)
    kw = {} if clock is None else {"clock": clock}
    ctx = Ctx(cfg, store, RateLimiter(), **kw)
    docs = None if not cfg.enable_docs else "/docs"
    app = FastAPI(title="VPNGate backend", docs_url=docs, redoc_url=None,
                  openapi_url="/openapi.json" if cfg.enable_docs else None)
    app.include_router(build_router(ctx))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > cfg.max_request_bytes):
            return JSONResponse(error_body("payload_too_large", "Request body too large."), status_code=413)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e.get("loc", ()) if p != "body") for e in exc.errors()][:10]
        return JSONResponse(error_body("invalid_request", "Request validation failed.", fields), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, "Request could not be served."), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(error_body("internal_error", "Internal server error."), status_code=500)

    return app
