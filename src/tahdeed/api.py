"""FastAPI service: /resolve, /resolve/batch (CSV), /health, plus the static dashboard."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .service import load_resolver
from .standardize import resolution_json

WEB = Path(__file__).resolve().parents[2] / "web"
MAX_BATCH = 5000


class ResolveRequest(BaseModel):
    address: str


def create_app(resolver=None) -> FastAPI:
    app = FastAPI(title="tahdeed", version=__version__,
                  description="Bilingual UAE address resolver with calibrated confidence.")  # fmt: skip
    state = {"r": resolver}

    def R():
        if state["r"] is None:
            state["r"] = load_resolver()
        return state["r"]

    @app.get("/health")
    def health():
        r = R()
        return {"status": "ok", "version": __version__, "gazetteer": r.g.stats(),
                "ranker": getattr(r.ranker, "name", "none")}  # fmt: skip

    @app.post("/resolve")
    def resolve(req: ResolveRequest):
        if not req.address.strip():
            raise HTTPException(422, "address is empty")
        return resolution_json(R().resolve(req.address[:500]))

    @app.post("/resolve/batch")
    async def batch(file: UploadFile = File(...)):
        """CSV with an ``address`` column -> CSV with coordinates, status and confidence."""
        raw = (await file.read()).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows or "address" not in rows[0]:
            raise HTTPException(422, "CSV needs an 'address' column")
        if len(rows) > MAX_BATCH:
            raise HTTPException(413, f"max {MAX_BATCH} rows per request")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["address", "status", "lat", "lon", "radius_m", "p_within_50m",
                    "p_correct_at_tier", "tier", "standard_en", "standard_ar", "asks"])  # fmt: skip
        for row in rows:
            j = resolution_json(R().resolve(row["address"][:500]))
            b = j["best"]
            w.writerow([row["address"], j["status"], *(
                [b["lat"], b["lon"], b["radius_m"], b["p_within_50m"], b["p_correct_at_tier"],
                 b["tier"], b["standard"]["en"], b["standard"]["ar"]] if b else [""] * 8
            ), " | ".join(j["asks"])])  # fmt: skip
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
