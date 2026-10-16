"""Measure the service's real memory on Linux: load it as the server would, answer queries, read
``/proc/self/status``.

    TAHDEED_STRICT=1 python deploy/measure_rss.py --db region/gazetteer.sqlite \
        --model region/ranker.npz --out docs/region_rss.json

It imports FastAPI and uvicorn (as the server process does), builds the app with the resolver
loaded in strict mode (a missing or mismatched model fails), answers a fixed list of queries
through the app, and records VmRSS (resident now) and VmHWM (peak resident) in MB, the load time
and the gazetteer row counts. Linux only (needs ``/proc``).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path

QUERIES = [
    "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi",
    "٢٩ شارع شبيب بن سعيد المهيري، الخالدية، أبوظبي",
    "3 Al Mayameen 5 Strit, Al Noud, Al Ain",
    "Shabib Bin Saeed Al Muhairi Street, Khalidiyah",
    "near Abu Dhabi Mall, Abu Dhabi",
    "Corniche Road, Abu Dhabi",
    "Villa 12, Street 5, Mohammed Bin Zayed City",
    "P.O. Box 12345, Abu Dhabi",
]


def proc_status() -> dict[str, float]:
    out: dict[str, float] = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM"):
            out[k] = round(int(v.split()[0]) / 1024, 1)  # kB -> MB
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rounds", type=int, default=50, help="passes over the query list")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import uvicorn  # noqa: F401  (the server process imports it)
    from fastapi.testclient import TestClient

    # one in-process client sends every request: switch the limiter off for the measurement only
    os.environ["TAHDEED_RATE_LIMIT"] = "0"
    base = proc_status()
    from tahdeed.api import create_app
    from tahdeed.service import load_resolver

    t0 = time.perf_counter()
    r = load_resolver(Path(a.db), Path(a.model), strict=True)
    load_s = time.perf_counter() - t0
    loaded = proc_status()
    client = TestClient(create_app(r))
    statuses: dict[str, int] = {}
    t1 = time.perf_counter()
    for _ in range(a.rounds):
        for q in QUERIES:
            j = client.post("/resolve", json={"address": q}).json()
            statuses[j["status"]] = statuses.get(j["status"], 0) + 1
    ms = (time.perf_counter() - t1) * 1000 / (a.rounds * len(QUERIES))
    after = proc_status()
    res = {
        "db": Path(a.db).name,
        "gazetteer_sha256": r.g.sha256,
        "gazetteer_rows": r.g.stats(),
        "model_arrays_sha256": r.ranker.manifest["arrays_sha256"],
        "degraded": bool(r.degraded_reason),
        "python": platform.python_version(),
        "baseline_mb": base,
        "after_load_mb": loaded,
        "after_queries_mb": after,
        "load_seconds": round(load_s, 2),
        "requests": a.rounds * len(QUERIES),
        "mean_ms_per_request_in_process": round(ms, 2),
        "statuses": statuses,
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
