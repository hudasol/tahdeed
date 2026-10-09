"""Hand-written gold set: realistic queries written by a person, not by a generator.

Truth is the registry record the query was written about (coordinates taken from the gazetteer),
so this measures end-to-end behaviour on human phrasing. It is small (40 rows): a smoke test of
the generator-gap finding, not a benchmark to quote precision from.
"""

from __future__ import annotations

import json
from pathlib import Path

from .geo import haversine_m

GOLD = Path(__file__).resolve().parents[2] / "tests" / "gold" / "gold_v1.json"


def run_gold(resolver, path: str | Path = GOLD) -> dict:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    out, status = [], {}
    for r in rows:
        res = resolver.resolve(r["query"])
        status[res.status] = status.get(res.status, 0) + 1
        b = res.best
        d = haversine_m(b.lat, b.lon, r["lat"], r["lon"]) if b else None
        out.append({"query": r["query"], "status": res.status, "tier": b.tier if b else None,
                    "dist_m": None if d is None else round(d), "p50": b.p50 if b else None})  # fmt: skip
    n = len(rows)
    ds = [o["dist_m"] for o in out]
    res_ = [o for o in out if o["status"] == "resolved"]
    return {
        "n": n,
        "status": status,
        "top1_within_50m": sum(1 for d in ds if d is not None and d <= 50) / n,
        "top1_within_500m": sum(1 for d in ds if d is not None and d <= 500) / n,
        "resolved": len(res_),
        "resolved_within_50m": sum(1 for o in res_ if o["dist_m"] <= 50),
        "rows": out,
    }
