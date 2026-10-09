"""FastAPI service: /resolve, /resolve/batch (CSV), /health, /config, plus the static dashboard.

Hardening: security headers, request-size limit, optional bearer token (``TAHDEED_API_TOKEN``),
request ids, privacy-preserving audit log, no stack traces in responses, explicit ``degraded`` flag
when the calibrated model is unavailable.
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .audit import record
from .service import load_resolver
from .standardize import resolution_json

log = logging.getLogger("tahdeed")
WEB = Path(__file__).resolve().parents[2] / "web"
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


def create_app(resolver=None) -> FastAPI:
    app = FastAPI(
        title="tahdeed",
        version=__version__,
        description="Bilingual UAE address resolver with calibrated confidence.",
        docs_url="/docs",
        redoc_url=None,
    )
    state = {"r": resolver}
    token = os.environ.get("TAHDEED_API_TOKEN")

    def R():
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
        return {"tile_url": TILE_URL, "version": __version__}

    def _one(text: str, rid: str | None = None) -> dict:
        t0 = time.perf_counter()
        j = resolution_json(R().resolve(text))
        ms = (time.perf_counter() - t0) * 1000
        j["degraded"] = bool(R().degraded_reason)
        j["calibrated"] = not j["degraded"]
        record(text, j, ms, versions(), rid)
        return j

    @app.post("/resolve")
    def resolve(req: ResolveRequest, request: Request):
        if not req.address.strip():
            raise HTTPException(422, "address is empty")
        return _one(req.address, request.headers.get("x-request-id"))

    @app.post("/resolve/batch")
    async def batch(file: UploadFile = File(...)):  # noqa: B008
        """CSV with an ``address`` column -> CSV with coordinates, status and confidence."""
        raw = (await file.read(MAX_BODY_BYTES + 1)).decode("utf-8-sig", errors="replace")
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, "file too large")
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows or "address" not in rows[0]:
            raise HTTPException(422, "CSV needs an 'address' column")
        if len(rows) > MAX_BATCH:
            raise HTTPException(413, f"max {MAX_BATCH} rows per request")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["address", "status", "lat", "lon", "radius_m", "p_within_50m", "p_within_1km",
                    "tier", "standard_en", "standard_ar", "asks", "calibrated"])  # fmt: skip
        for row in rows:
            j = _one((row.get("address") or "")[:500])
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


def app_factory() -> FastAPI:
    return create_app()
