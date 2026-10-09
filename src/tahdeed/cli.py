"""``tahdeed`` command line: build | train | resolve | batch | eval | serve."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tahdeed", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the gazetteer from an OSM .pbf extract")
    b.add_argument("pbf")
    b.add_argument("--out", default="data/gazetteer.sqlite")

    t = sub.add_parser("train", help="train + calibrate the ranker")
    t.add_argument("--db", default="data/gazetteer.sqlite")
    t.add_argument("--out", default="data/models/ranker.pkl")
    t.add_argument("--n-train", type=int, default=30000)
    t.add_argument("--workers", type=int, default=2)

    r = sub.add_parser("resolve", help="resolve one address")
    r.add_argument("address")
    r.add_argument("--json", action="store_true")

    ba = sub.add_parser("batch", help="resolve a CSV with an 'address' column")
    ba.add_argument("infile")
    ba.add_argument("outfile")

    e = sub.add_parser("eval", help="run the evaluation harness")
    e.add_argument("--db", default="data/gazetteer.sqlite")
    e.add_argument("--model", default="data/models/ranker.pkl")
    e.add_argument("--n", type=int, default=6000)
    e.add_argument("--nominatim", type=int, default=0)
    e.add_argument("--out", default="data/eval_results.json")

    s = sub.add_parser("serve", help="run the API + dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    a = ap.parse_args(argv)

    if a.cmd == "build":
        from .build import build

        build(a.pbf, a.out)
    elif a.cmd == "train":
        from .gazetteer import Gazetteer
        from .train import train

        g = Gazetteer.load(a.db)
        ranker, _ = train(g, n_train=a.n_train, n_calib=a.n_train // 3, workers=a.workers)
        ranker.save(a.out)
        print(f"saved {a.out}")
    elif a.cmd == "resolve":
        from .service import load_resolver
        from .standardize import resolution_json

        j = resolution_json(load_resolver().resolve(a.address))
        if a.json:
            print(json.dumps(j, ensure_ascii=False, indent=2))
        else:
            _pretty(j)
    elif a.cmd == "batch":
        from .service import load_resolver
        from .standardize import resolution_json

        res = load_resolver()
        with (
            open(a.infile, newline="", encoding="utf-8-sig") as fh,
            open(a.outfile, "w", newline="", encoding="utf-8") as out,
        ):
            w = csv.writer(out)
            w.writerow(["address", "status", "lat", "lon", "radius_m", "p_within_50m", "tier",
                        "standard_en", "asks"])  # fmt: skip
            for row in csv.DictReader(fh):
                j = resolution_json(res.resolve(row["address"]))
                bst = j["best"] or {}
                w.writerow([row["address"], j["status"], bst.get("lat", ""), bst.get("lon", ""),
                            bst.get("radius_m", ""), bst.get("p_within_50m", ""),
                            bst.get("tier", ""), (bst.get("standard") or {}).get("en", ""),
                            " | ".join(j["asks"])])  # fmt: skip
    elif a.cmd == "eval":
        from .calibrate import GBMRanker
        from .evaluate import evaluate, to_markdown
        from .gazetteer import Gazetteer

        g = Gazetteer.load(a.db)
        res = evaluate(g, GBMRanker.load(a.model), n_addr=a.n, n_hole=a.n // 2,
                       nominatim=a.nominatim)  # fmt: skip
        Path(a.out).write_text(json.dumps(res, indent=1, default=float))
        print(to_markdown(res))
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("tahdeed.api:app_factory", factory=True, host=a.host, port=a.port)
    return 0


def _pretty(j: dict) -> None:
    b = j["best"]
    print(f"status: {j['status']}")
    if b:
        print(f"point : {b['lat']}, {b['lon']}  (±{b['radius_m']} m, tier={b['tier']})")
        print(f"conf  : P(≤50 m)={b['p_within_50m']}  P(correct at tier)={b['p_correct_at_tier']}")
        print(f"en    : {b['standard']['en']}\nar    : {b['standard']['ar']}")
    for q in j["asks"]:
        print(f"ask   : {q}")
    for n in j["notes"]:
        print(f"note  : {n}")


if __name__ == "__main__":
    sys.exit(main())
