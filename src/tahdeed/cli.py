"""``tahdeed`` command line: build | train | resolve | batch | eval | serve."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from json import dump as json_dump
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    # `bench build|baseline|baselines|score|report|fetch-external` is Gulf-AddressBench; bare
    # `bench` stays the latency test.
    bench_cmds = {"build", "baseline", "baselines", "score", "report", "fetch-external"}
    if args[:1] == ["bench"] and args[1:2] and args[1] in bench_cmds:
        from .bench import main as bench_main

        return bench_main(args[1:])
    if args[:1] == ["human"]:
        from .human import main as human_main

        return human_main(args[1:])
    ap = argparse.ArgumentParser(prog="tahdeed", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the gazetteer from an OSM .pbf extract")
    b.add_argument("pbf")
    b.add_argument("--out", default="data/gazetteer.sqlite")

    t = sub.add_parser("train", help="train + calibrate the ranker")
    t.add_argument("--db", default="data/gazetteer.sqlite")
    t.add_argument("--out", default="data/models/ranker.npz")
    t.add_argument("--n-train", type=int, default=30000)
    t.add_argument("--seed", type=int, default=0, help="query-generation seed (default 0)")
    t.add_argument("--workers", type=int, default=2)
    t.add_argument("--hole-rate", type=float, default=0.30)
    t.add_argument("--no-crosscity-mix", action="store_true", help="ablation: v2.0 training mix")
    t.add_argument(
        "--no-poi-hole", action="store_true", help="cross-city mix without its poi_hole stratum"
    )
    t.add_argument(
        "--mask-features", default="", help="comma list of features held at -1 (ablation)"
    )

    r = sub.add_parser("resolve", help="resolve one address")
    r.add_argument("address")
    r.add_argument("--json", action="store_true")
    r.add_argument("--city", default=None, help='answer to "Which city?" (key or name)')

    ba = sub.add_parser("batch", help="resolve a CSV with an 'address' column")
    ba.add_argument("infile")
    ba.add_argument("outfile")
    ba.add_argument("--workers", type=int, default=1)

    st = sub.add_parser(
        "studies", help="generator gap, ablations, baselines (writes docs/studies.json)"
    )
    st.add_argument("--n", type=int, default=2500)
    st.add_argument("--h0", default=None, help="model trained without hole examples (ablation)")
    st.add_argument("--out", default="docs/studies.json")

    fg = sub.add_parser("figures", help="draw the doc figures from the JSON results")
    fg.add_argument("--eval", default="docs/eval.json")
    fg.add_argument("--studies", default="docs/studies.json")
    fg.add_argument("--out", default="docs/figures")

    sub.add_parser("verify", help="check gazetteer / model provenance and integrity")

    cc = sub.add_parser("crosscity", help="cross-city confident-wrong-city experiment")
    cc.add_argument("--split", default="dev")
    cc.add_argument("--out", default="docs/crosscity_dev.json")
    cc.add_argument("--margins", default=None, help="comma list; default: the full sweep")
    ab = sub.add_parser("ablate-poi", help="POI calibration ablation over trained models (dev)")
    ab.add_argument("models", help="comma list name=path.npz")
    ab.add_argument("--db", default="data/gazetteer.sqlite")
    ab.add_argument("--out", default="docs/poi_ablation.json")
    ab.add_argument("--workers", type=int, default=2)
    ab.add_argument("--no-crosscity", action="store_true")
    cl = sub.add_parser("clarify", help='T2: answer "Which city?" with the true city (dev)')
    cl.add_argument("--db", default="data/gazetteer.sqlite")
    cl.add_argument("--model", default="data/models/ranker.npz")
    cl.add_argument("--out", default="docs/clarify_dev.json")
    cl.add_argument("--workers", type=int, default=2)
    go = sub.add_parser("gold", help="evaluate on the hand-written gold set")
    go.add_argument("--out", default=None)
    sub.add_parser("human", help="human-written query set: ingest | evaluate (see bench/human_kit)")
    be = sub.add_parser(
        "bench",
        help="latency, throughput, memory; or `bench build|baseline|score|report` (Gulf-AddressBench)",
    )
    be.add_argument("--n", type=int, default=2000)
    be.add_argument("--json", action="store_true")

    e = sub.add_parser("eval", help="run the evaluation harness")
    e.add_argument("--db", default="data/gazetteer.sqlite")
    e.add_argument("--model", default="data/models/ranker.npz")
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
        from .train import MixOptions, train

        g = Gazetteer.load(a.db)
        masked = tuple(x.strip() for x in a.mask_features.split(",") if x.strip())
        mix = MixOptions(
            crosscity=not a.no_crosscity_mix,
            crosscity_poi_hole=not a.no_poi_hole,
            mask_features=masked,
        )
        ranker, _ = train(
            g,
            n_train=a.n_train,
            n_calib=a.n_train // 3,
            workers=a.workers,
            hole_rate=a.hole_rate,
            mix=mix,
            seed=a.seed,
        )
        from .model_io import export

        meta = {"n_train": a.n_train, "hole_rate": a.hole_rate, "seed": a.seed, **mix.manifest()}
        export(ranker, a.out, g.sha256, meta)
        print(f"saved {a.out}")
    elif a.cmd == "resolve":
        from .service import load_resolver
        from .standardize import resolution_json

        try:
            j = resolution_json(load_resolver().resolve(a.address, city=a.city))
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(j, ensure_ascii=False, indent=2))
        else:
            _pretty(j)
    elif a.cmd == "batch":
        _batch(a.infile, a.outfile, a.workers)
    elif a.cmd == "studies":
        from .gazetteer import Gazetteer
        from .model_io import load as load_model
        from .studies import main as run_studies

        g = Gazetteer.load(a.db if hasattr(a, "db") else "data/gazetteer.sqlite")
        rk = load_model("data/models/ranker.npz", gazetteer_sha256=g.sha256)
        h0 = load_model(a.h0, gazetteer_sha256=g.sha256) if a.h0 else None
        run_studies(g, rk, h0, a.out, a.n)
        print(f"wrote {a.out}")
    elif a.cmd == "figures":
        from .figures import make_all

        print("figures:", ", ".join(make_all(a.eval, a.studies, a.out)))
    elif a.cmd == "verify":
        return _verify()
    elif a.cmd == "crosscity":
        from .crosscity import MARGINS, run_crosscity
        from .gazetteer import Gazetteer
        from .model_io import load as load_model

        g = Gazetteer.load("data/gazetteer.sqlite")
        rk = load_model("data/models/ranker.npz", gazetteer_sha256=g.sha256)
        ms = tuple(float(x) for x in a.margins.split(",")) if a.margins else MARGINS
        res = run_crosscity(g, rk, a.split, margins=ms)
        with open(a.out, "w") as fh:
            json_dump(res, fh, indent=1, default=float)
        print("wrote", a.out)
    elif a.cmd == "ablate-poi":
        from .poi_ablation import run as run_ablation

        models = dict(x.split("=", 1) for x in a.models.split(",") if x)
        run_ablation(models, a.db, a.out, workers=a.workers, crosscity=not a.no_crosscity)
        print("wrote", a.out)
    elif a.cmd == "clarify":
        from .clarify import run as run_clarify

        res = run_clarify(a.db, a.model, a.out, workers=a.workers)
        print(json.dumps(res["groups"]["non_hole"], default=float)[:400])
        print("wrote", a.out)
    elif a.cmd == "gold":
        return _gold(a.out)
    elif a.cmd == "bench":
        return _bench(a.n, a.json)
    elif a.cmd == "eval":
        from .evaluate import evaluate, to_markdown
        from .gazetteer import Gazetteer
        from .model_io import load as load_model

        g = Gazetteer.load(a.db)
        ranker = load_model(a.model, gazetteer_sha256=g.sha256)
        res = evaluate(g, ranker, n_addr=a.n, n_hole=a.n // 2, nominatim=a.nominatim)
        Path(a.out).write_text(json.dumps(res, indent=1, default=float))
        print(to_markdown(res))
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("tahdeed.api:app_factory", factory=True, host=a.host, port=a.port)
    return 0


_R = None


def _resolve_row(text: str) -> dict:
    from .standardize import resolution_json

    return resolution_json(_R.resolve(text[:500]))


def _batch(infile: str, outfile: str, workers: int) -> None:
    import multiprocessing as mp

    from .service import load_resolver

    global _R
    _R = load_resolver()
    with open(infile, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "address" not in rows[0]:
        raise SystemExit("input CSV needs an 'address' column")
    texts = [r["address"] for r in rows]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            results = pool.map(_resolve_row, texts, chunksize=64)
    else:
        results = [_resolve_row(t) for t in texts]
    with open(outfile, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["address", "status", "lat", "lon", "radius_m", "p_within_50m", "p_within_1km",
                    "tier", "standard_en", "asks", "calibrated"])  # fmt: skip
        for t, j in zip(texts, results, strict=True):
            b = j["best"] or {}
            w.writerow([t, j["status"], b.get("lat", ""), b.get("lon", ""), b.get("radius_m", ""),
                        b.get("p_within_50m", ""), b.get("p_within_1km", ""), b.get("tier", ""),
                        (b.get("standard") or {}).get("en", ""), " | ".join(j["asks"]),
                        not bool(_R.degraded_reason)])  # fmt: skip
    print(f"resolved {len(texts)} addresses -> {outfile}")


def _verify() -> int:
    from .gazetteer import Gazetteer
    from .model_io import ModelMismatch
    from .model_io import load as load_model
    from .service import DEFAULT_DB, DEFAULT_MODEL

    g = Gazetteer.load(DEFAULT_DB)
    print(f"gazetteer  {DEFAULT_DB}  sha256={g.sha256[:16]}  schema={g.meta.get('schema')}")
    print(f"           source={g.meta.get('source')}  built_at={g.meta.get('built_at')}")
    try:
        m = load_model(DEFAULT_MODEL, gazetteer_sha256=g.sha256)
        mf = m.manifest
        print(
            f"model      {DEFAULT_MODEL}  arrays_sha256={mf['arrays_sha256'][:16]}  tau={mf['policy']['tau']}"
        )
        print("OK: model matches code (feature list) and gazetteer, checksum valid")
        return 0
    except (ModelMismatch, OSError) as ex:
        print(f"FAIL: {ex}")
        return 1


def _gold(out: str | None) -> int:
    import json

    from .gold import run_gold
    from .service import load_resolver

    res = run_gold(load_resolver())
    if out:
        with open(out, "w") as fh:
            json.dump(res, fh, indent=1, ensure_ascii=False)
    print({k: v for k, v in res.items() if k != "rows"})
    for r in res["rows"]:
        if r["dist_m"] is None or r["dist_m"] > 50:
            print(r)
    return 0


def _bench(n: int, as_json: bool) -> int:
    import resource
    import time

    import numpy as np

    from .noise import make_address_queries
    from .service import load_resolver

    t0 = time.perf_counter()
    r = load_resolver()
    load_s = time.perf_counter() - t0
    qs = make_address_queries(r.g, n, "dev", seed=99)
    lat = []
    for q in qs[:50]:  # warm-up
        r.resolve(q.text)
    for q in qs:
        t = time.perf_counter()
        r.resolve(q.text)
        lat.append((time.perf_counter() - t) * 1000)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    out = {"n": len(lat), "load_seconds": round(load_s, 2), "rss_mb": round(rss_mb),
           "ms_p50": round(float(np.percentile(lat, 50)), 2), "ms_p95": round(float(np.percentile(lat, 95)), 2),
           "ms_p99": round(float(np.percentile(lat, 99)), 2), "ms_max": round(max(lat), 1),
           "qps_single_core": round(1000 / float(np.mean(lat)), 1)}  # fmt: skip
    print(json.dumps(out) if as_json else "\n".join(f"{k:>16}: {v}" for k, v in out.items()))
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
    if j.get("city_options"):
        keys = ", ".join(o["key"] for o in j["city_options"])
        print(f"retry : add --city with one of: {keys}")
    for n in j["notes"]:
        print(f"note  : {n}")


if __name__ == "__main__":
    sys.exit(main())
