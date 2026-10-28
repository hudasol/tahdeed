"""FastAPI service: /resolve, /resolve/batch (CSV), /health, /config, plus the static dashboard.

Hardening: security headers, request-size limit, optional bearer token (``TAHDEED_API_TOKEN``),
request ids, privacy-preserving audit log, no stack traces in responses, explicit ``degraded`` flag
when the calibrated model is unavailable, and a per-client token-bucket rate limiter
(``TAHDEED_RATE_LIMIT`` requests/minute, default 60, ``0`` = off; ``/health`` is exempt;
``X-Forwarded-For`` is honoured only with ``TAHDEED_TRUST_PROXY=1``).
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .audit import record
from .geo import CITIES
from .privacy import redact_pii
from .ratelimit import TokenBucketLimiter, batch_cost, burst_for, client_key, parse_limit
from .resolve import city_key
from .service import load_resolver
from .standardize import resolution_json

log = logging.getLogger("tahdeed")


def _find_web() -> Path:
    """Dashboard directory: ``TAHDEED_WEB``, else the ``web`` package data shipped with tahdeed."""
    cands = [os.environ.get("TAHDEED_WEB"), Path(__file__).resolve().parent / "web"]
    for c in cands:
        if c and Path(c).is_dir():
            return Path(c).resolve()
    return Path(__file__).resolve().parent / "web"


WEB = _find_web()
ATTRIBUTION = (
    "Contains information from OpenStreetMap, © OpenStreetMap contributors, "
    "available under the Open Database Licence (ODbL) 1.0."
)
LIMITED_PREFIX = "/resolve"  # /resolve and /resolve/batch; /health, /config and static are exempt
MAX_BATCH = 5000
MAX_BODY_BYTES = 2_000_000
TILE_URL = os.environ.get("TAHDEED_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    ),
}


class ResolveRequest(BaseModel):
    address: str = Field(..., max_length=2000)
    # optional answer to "Which city?": a key from `city_options` in an earlier response, or a
    # city name (English or Arabic); unknown values are rejected with 422
    city: str | None = Field(None, max_length=40)


def create_app(resolver=None) -> FastAPI:
    load_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # In strict mode a missing or mismatched model must stop the process at start, not on the
        # first request, so the orchestrator sees a failed start rather than a healthy dead service.
        if os.environ.get("TAHDEED_STRICT", "0") == "1":
            R()
        yield

    app = FastAPI(
        lifespan=lifespan,
        title="tahdeed",
        version=__version__,
        description="Bilingual UAE address resolver with calibrated confidence.",
        docs_url="/docs",
        redoc_url=None,
    )
    state = {"r": resolver}
    token = os.environ.get("TAHDEED_API_TOKEN")
    per_minute = parse_limit(os.environ.get("TAHDEED_RATE_LIMIT"))
    limiter = TokenBucketLimiter(per_minute, burst_for(per_minute)) if per_minute > 0 else None
    app.state.limiter = limiter
    trust_proxy = os.environ.get("TAHDEED_TRUST_PROXY") == "1"
    try:
        proxy_hops = max(1, int(os.environ.get("TAHDEED_PROXY_HOPS", "1")))
    except ValueError:
        proxy_hops = 1

    def who(request: Request) -> str:
        peer = request.client.host if request.client else None
        return client_key(peer, request.headers, trust_proxy=trust_proxy, proxy_hops=proxy_hops)

    def too_many(retry: int) -> JSONResponse:
        return JSONResponse(
            {"error": "rate limit exceeded", "retry_after_seconds": retry},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )

    def R():
        if state["r"] is None:
            with load_lock:
                if state["r"] is None:
                    state["r"] = load_resolver()
        return state["r"]

    def versions() -> dict:
        r = R()
        return {
            "version": __version__,
            "gazetteer": r.g.sha256[:12],
            "model": (getattr(r.ranker, "manifest", {}) or {}).get("arrays_sha256", "")[:12],
            "degraded": bool(r.degraded_reason),
        }

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > MAX_BODY_BYTES:
            return JSONResponse({"error": "request too large"}, status_code=413)
        if limiter is not None and request.url.path.startswith(LIMITED_PREFIX):
            ok, retry = limiter.check(who(request))
            if not ok:
                resp = too_many(retry)
                resp.headers["X-Request-ID"] = rid
                for k, v in SECURITY_HEADERS.items():
                    resp.headers[k] = v
                return resp
        if token and request.url.path.startswith("/resolve"):
            got = request.headers.get("authorization", "")
            if not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            resp = await call_next(request)
        except Exception:  # never leak internals
            log.exception("unhandled error request_id=%s", rid)
            resp = JSONResponse({"error": "internal error", "request_id": rid}, status_code=500)
        for k, v in SECURITY_HEADERS.items():
            resp.headers[k] = v
        resp.headers["X-Request-ID"] = rid
        return resp

    @app.get("/health")
    def health():
        r = R()
        return {
            "status": "degraded" if r.degraded_reason else "ok",
            "degraded_reason": r.degraded_reason,
            **versions(),
            "gazetteer_stats": r.g.stats(),
            "ranker": getattr(r.ranker, "name", "none"),
        }

    @app.get("/config")
    def config():
        return {
            "tile_url": TILE_URL,
            "version": __version__,
            # ODbL notice for a public instance (see docs/DEPLOYMENT.md); the dashboard may show it
            "attribution": ATTRIBUTION,
            "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "data_offer_url": os.environ.get("TAHDEED_DATA_OFFER_URL") or None,
        }

    def _one(text: str, rid: str | None = None, city: str | None = None) -> dict:
        t0 = time.perf_counter()
        j = resolution_json(R().resolve(text, city=city or None))
        ms = (time.perf_counter() - t0) * 1000
        j["degraded"] = bool(R().degraded_reason)
        j["calibrated"] = not j["degraded"]
        # PII guard before anything is logged (the resolver redacts too; this keeps the audit
        # record independent of that). Without TAHDEED_LOG_RAW=1 only a hash of this is logged.
        safe, _ = redact_pii(text)
        # the city hint is a validated city key (never free text), so it is logged as is
        record(safe, j, ms, {**versions(), "city_hint": j.get("city_hint")}, rid)
        return j

    def _check_city(city: str | None) -> None:
        if city and city_key(city) is None:
            raise HTTPException(
                422, "unknown city; valid keys: " + ", ".join(c.key for c in CITIES)
            )

    @app.post("/resolve")
    def resolve(req: ResolveRequest, request: Request):
        if not req.address.strip():
            raise HTTPException(422, "address is empty")
        _check_city(req.city)
        return _one(req.address, request.headers.get("x-request-id"), req.city)

    @app.post("/resolve/batch")
    async def batch(request: Request, file: UploadFile = File(...)):  # noqa: B008
        """CSV with an ``address`` column (and optional ``city``) -> CSV with coordinates, status
        and confidence. An unknown ``city`` value is ignored for that row and noted in ``asks``."""
        raw = (await file.read(MAX_BODY_BYTES + 1)).decode("utf-8-sig", errors="replace")
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, "file too large")
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows or "address" not in rows[0]:
            raise HTTPException(422, "CSV needs an 'address' column")
        if len(rows) > MAX_BATCH:
            raise HTTPException(413, f"max {MAX_BATCH} rows per request")
        if limiter is not None:  # middleware charged 1; a batch costs 1 per 50 rows (min 1)
            extra = batch_cost(len(rows)) - 1
            if extra > 0:
                ok, retry = limiter.check(who(request), extra)
                if not ok:
                    return too_many(retry)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["address", "status", "lat", "lon", "radius_m", "p_within_50m", "p_within_1km",
                    "tier", "standard_en", "standard_ar", "asks", "calibrated"])  # fmt: skip
        for row in rows:
            ch = (row.get("city") or "").strip()[:40] or None
            if ch and city_key(ch) is None:
                j = _one((row.get("address") or "")[:500])
                j["asks"] = ["Unknown city value ignored.", *j["asks"]]
            else:
                j = _one((row.get("address") or "")[:500], city=ch)
            b = j["best"]
            w.writerow([row.get("address", ""), j["status"], *(
                [b["lat"], b["lon"], b["radius_m"], b["p_within_50m"], b["p_within_1km"],
                 b["tier"], b["standard"]["en"], b["standard"]["ar"]] if b else [""] * 8
            ), " | ".join(j["asks"]), j["calibrated"]])  # fmt: skip
        return Response(out.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=resolved.csv"})  # fmt: skip

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB / "index.html")

    return app


def _configure_logging() -> None:
    """Make the ``tahdeed`` loggers (audit records, warnings) visible on stdout under uvicorn.

    uvicorn only configures its own loggers, so without this the audit log would be dropped.
    A process that already configured logging is left alone.
    """
    lg = logging.getLogger("tahdeed")
    if lg.handlers or logging.getLogger().handlers:
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    lg.addHandler(h)
    lg.setLevel(logging.INFO)


def app_factory() -> FastAPI:
    _configure_logging()
    return create_app()
