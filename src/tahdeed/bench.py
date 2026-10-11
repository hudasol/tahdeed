"""Gulf-AddressBench: dataset export, baselines and the scorer.

    tahdeed bench build     [--db ...] [--out bench/data]      export the versioned datasets
    tahdeed bench baseline  {naive,tahdeed,nominatim} --set S [--out preds.jsonl]
    tahdeed bench score     predictions.jsonl [--data bench/data] [--json out.json]
    tahdeed bench report    [--results bench/results] [--out docs/BENCH_REPORT.md]

Everything here is deterministic given the gazetteer snapshot: dataset files carry the seeds and a
SHA-256 manifest. Scoring needs only the dataset files, not the gazetteer. See ``bench/README.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

from .geo import haversine_m, nearest_city

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bench" / "data"
RESULTS = ROOT / "bench" / "results"
RADII = (50, 200, 1000)

# name -> (generator, split, n, seed, status, description). `status` records contamination.
SETS = {
    "address_dev": (
        "addr_v2",
        "dev",
        1500,
        101,
        "dev-seen",
        "synthetic structured addresses, mixed noise",
    ),
    "address_sealed": ("addr_v2", "sealed", 600, 102, "sealed", "same generator, sealed districts"),
    "hole_dev": ("addr_hole", "dev", 600, 103, "dev-seen", "truth record absent from the index"),
    "hole_sealed": (
        "addr_hole",
        "sealed",
        300,
        104,
        "sealed",
        "truth record absent, sealed districts",
    ),
    "poi_dev": ("poi", "dev", 600, 105, "dev-seen", "POI name (+ street) + city"),
    "poi_sealed": ("poi", "sealed", 300, 106, "sealed", "POI, sealed districts"),
    "landmark_dev": (
        "landmark",
        "dev",
        400,
        107,
        "dev-seen",
        "'near <landmark>' relational queries",
    ),
    "crosscity_dev": (
        "crosscity",
        "dev",
        450,
        0,
        "dev-seen",
        "names present in several cities; E0/E1/E2",
    ),
    "crosscity_sealed": ("crosscity", "sealed", 450, 0, "sealed-used-once", "cross-city, sealed"),
}


# ----------------------------------------------------------------------------- build


def _row(i: int, name: str, split: str, q, g) -> dict:
    if q.truth_kind == "addr":
        a = g.addr[q.truth_idx]
        city, ref = a[8], f"addr/{a[14]}"
    else:
        p = g.pois[q.truth_idx]
        city, ref = p[6], f"poi/{p[10]}"
    return {
        "id": f"{name}-{i:05d}",
        "set": name,
        "split": split,
        "text": q.text,
        "lang": q.lang,
        "kind": q.truth_kind,
        "lat": round(q.lat, 7),
        "lon": round(q.lon, 7),
        "truth_city": city,
        "truth_city_geo": nearest_city(q.lat, q.lon).key,
        "truth_ref": ref,  # OSM element; hole rows: this record is absent from the reference index
        "hole": bool(q.hidden),
        "stratum": q.extra.get("stratum") or q.slice,
        "evidence": q.extra.get("evidence"),
        "noise": list(q.noise),
        "synthetic": True,
    }


def build(db: str, out: Path) -> dict:
    from .crosscity import make_crosscity_queries
    from .gazetteer import Gazetteer
    from .noise import make_address_queries, make_poi_queries
    from .noise2 import make_address_queries_v2, make_landmark_queries

    g = Gazetteer.load(db)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"version": VERSION, "gazetteer_sha256": g.sha256, "sets": {}}
    for name, (gen, split, n, seed, status, desc) in SETS.items():
        if gen == "addr_v2":
            qs = make_address_queries_v2(g, n, split, seed=seed)
        elif gen == "addr_hole":
            qs = make_address_queries(g, n, split, seed=seed, hole_rate=1.0)
        elif gen == "poi":
            qs = make_poi_queries(g, n, split, seed=seed)
        elif gen == "landmark":
            qs = make_landmark_queries(g, n, split, seed=seed)
        else:
            qs = make_crosscity_queries(g, split, n=n, seed=seed)
        rows = [_row(i, name, split, q, g) for i, q in enumerate(qs)]
        p = out / f"{name}.jsonl"
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        manifest["sets"][name] = {
            "n": len(rows), "generator": gen, "split": split, "seed": seed,
            "contamination": status, "description": desc,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }  # fmt: skip
        print(f"{name}: {len(rows)} rows")
    # hand-written gold set (40 rows, written by the maintainer during development: CONTAMINATED)
    gold = json.loads((ROOT / "tests" / "gold" / "gold_v1.json").read_text(encoding="utf-8"))
    p = out / "gold_handwritten.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for i, r in enumerate(gold):
            c = nearest_city(r["lat"], r["lon"]).key
            fh.write(json.dumps({
                "id": f"gold-{i:03d}", "set": "gold_handwritten", "split": "dev", "text": r["query"],
                "lang": "mixed", "kind": "addr", "lat": r["lat"], "lon": r["lon"], "truth_city": c, "truth_city_geo": c,
                "truth_ref": None, "hole": False, "stratum": "gold", "evidence": None, "noise": [],
                "synthetic": False,
            }, ensure_ascii=False) + "\n")  # fmt: skip
    manifest["sets"]["gold_handwritten"] = {
        "n": len(gold), "generator": "hand-written", "split": "dev", "seed": None,
        "contamination": "seen-throughout-development",
        "description": "40 queries written by the maintainer; truth = registry coordinates; truth_city is derived from coordinates",
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }  # fmt: skip
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


# ----------------------------------------------------------------------------- scoring


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [p, max(0.0, c - h), min(1.0, c + h)]


def load_rows(data: Path, sets: list[str] | None = None) -> list[dict]:
    rows = []
    for p in sorted(Path(data).glob("*.jsonl")):
        if sets and p.stem not in sets:
            continue
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]
    return rows


def read_predictions(path: str | Path) -> dict[str, dict]:
    """Validate the prediction file (see bench/PREDICTION_FORMAT.md)."""
    out: dict[str, dict] = {}
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as ex:
            raise ValueError(f"line {n}: not JSON ({ex})") from ex
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            raise ValueError(f"line {n}: needs a string 'id'")
        if r["id"] in out:
            raise ValueError(f"line {n}: duplicate id {r['id']}")
        has_loc = r.get("lat") is not None or r.get("lon") is not None
        if has_loc:
            la, lo = r.get("lat"), r.get("lon")
            if not (isinstance(la, (int, float)) and isinstance(lo, (int, float))):
                raise ValueError(f"line {n}: lat/lon must be numbers")
            if not (-90 <= la <= 90 and -180 <= lo <= 180):
                raise ValueError(f"line {n}: lat/lon out of range")
        if "abstain" in r and not isinstance(r["abstain"], bool):
            raise ValueError(f"line {n}: 'abstain' must be a boolean")
        c = r.get("confidence")
        if c is not None and not (isinstance(c, (int, float)) and 0 <= c <= 1):
            raise ValueError(f"line {n}: 'confidence' must be in [0, 1]")
        out[r["id"]] = r
    return out


def _ece(conf: list[float], hit: list[int], bins: int = 10) -> float:
    n = len(conf)
    if not n:
        return float("nan")
    tot = 0.0
    for b in range(bins):
        idx = [
            i
            for i, c in enumerate(conf)
            if b / bins <= c < (b + 1) / bins or (b == bins - 1 and c == 1)
        ]
        if idx:
            tot += (
                len(idx)
                / n
                * abs(sum(hit[i] for i in idx) / len(idx) - sum(conf[i] for i in idx) / len(idx))
            )
    return tot


def score_rows(rows: list[dict], preds: dict[str, dict]) -> dict:
    """Metrics over ``rows`` (all of which must have a prediction entry or count as abstained)."""
    n = len(rows)
    ans = a50 = a200 = a1k = f50 = f200 = f1k = cwc = 0
    errs: list[float] = []
    conf: list[float] = []
    hit: list[int] = []
    for r in rows:
        p = preds.get(r["id"]) or {}
        located = p.get("lat") is not None
        abstain = bool(p.get("abstain", False)) or not located
        d = haversine_m(p["lat"], p["lon"], r["lat"], r["lon"]) if located else None
        if d is not None:  # forced (ignores abstention)
            f50 += d <= 50
            f200 += d <= 200
            f1k += d <= 1000
        if abstain:
            continue
        ans += 1
        errs.append(d)
        a50 += d <= 50
        a200 += d <= 200
        a1k += d <= 1000
        if p.get("city"):  # tag semantics: compared with the record's city tag
            cwc += p["city"] != r["truth_city"]
        else:  # geometric semantics: nearest city centre on both sides
            cwc += nearest_city(p["lat"], p["lon"]).key != r["truth_city_geo"]
        if p.get("confidence") is not None:
            conf.append(float(p["confidence"]))
            hit.append(int(d <= 50))
    errs.sort()
    return {
        "n": n,
        "answered": wilson(ans, n),
        "precision_50m": wilson(a50, ans),
        "precision_200m": wilson(a200, ans),
        "precision_1km": wilson(a1k, ans),
        "confident_wrong_city": wilson(cwc, ans),
        "end_to_end_50m": wilson(a50, n),  # abstentions count as misses
        "forced_50m": wilson(f50, n),
        "forced_200m": wilson(f200, n),
        "forced_1km": wilson(f1k, n),
        "median_error_m": errs[len(errs) // 2] if errs else None,
        "ece_conf_50m": _ece(conf, hit) if conf else None,
        "n_with_confidence": len(conf),
    }


def score(pred_path: str | Path, data: Path = DATA, sets: list[str] | None = None) -> dict:
    preds = read_predictions(pred_path)
    rows = load_rows(data, sets)
    known = {r["id"] for r in rows}
    unknown = sorted(set(preds) - known)
    if unknown:
        raise ValueError(f"{len(unknown)} prediction ids not in the dataset, e.g. {unknown[:3]}")
    covered = {r["set"] for r in rows if r["id"] in preds}
    if not covered:
        raise ValueError("no prediction matches any dataset row")
    res: dict = {"version": VERSION, "sets": {}}
    for s in sorted(covered):
        rs = [r for r in rows if r["set"] == s]
        sub = {"overall": score_rows(rs, preds), "strata": {}}
        strata: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            strata[
                f"{r['stratum']}/{r['evidence']}" if r["evidence"] else str(r["stratum"])
            ].append(r)
        if len(strata) > 1:
            for k, v in sorted(strata.items()):
                sub["strata"][k] = score_rows(v, preds)
        sub["missing_predictions"] = sum(1 for r in rs if r["id"] not in preds)
        res["sets"][s] = sub
    return res


def _pct(x: list[float]) -> str:
    return f"{100 * x[0]:.1f}% [{100 * x[1]:.0f}-{100 * x[2]:.0f}]"


def print_score(res: dict, w=print) -> None:
    for s, sub in res["sets"].items():
        o = sub["overall"]
        w(f"\n{s}  (n={o['n']}, missing predictions: {sub['missing_predictions']})")
        w(f"  answered           {_pct(o['answered'])}")
        w(f"  precision@50m      {_pct(o['precision_50m'])}   (among answered)")
        w(f"  conf.wrong city    {_pct(o['confident_wrong_city'])}   (among answered)")
        w(f"  end-to-end@50m     {_pct(o['end_to_end_50m'])}   (abstain = miss)")
        w(f"  forced@50m/1km     {_pct(o['forced_50m'])} / {_pct(o['forced_1km'])}")
        if o["ece_conf_50m"] is not None:
            w(
                f"  ECE (confidence vs within-50m, n={o['n_with_confidence']}): {o['ece_conf_50m']:.3f}"
            )


# ----------------------------------------------------------------------------- baselines


def _naive_index(g):
    by_hn: dict[str, list[int]] = defaultdict(list)
    for i, hn in enumerate(g.addr_hn):
        by_hn[hn].append(i)
    return by_hn


def baseline_naive(rows: list[dict], db: str) -> list[dict]:
    """Token-set fuzzy match of the raw text against address strings sharing a house-number token.

    Address records only (no POIs/landmarks, no hole handling). Always answers when it finds a
    candidate; no confidence. Reference for 'what a few lines of rapidfuzz buys you'.
    """
    from rapidfuzz import fuzz

    from .gazetteer import Gazetteer
    from .normalize import normalize_text

    g = Gazetteer.load(db)
    by_hn = _naive_index(g)
    cache: dict[int, str] = {}

    def text_of(i: int) -> str:
        if i not in cache:
            a = g.addr[i]
            cache[i] = " ".join(x for x in (a[1], a[3], a[2], a[5], a[4], a[10], a[9]) if x).lower()
        return cache[i]

    out = []
    for r in rows:
        qt = normalize_text(r["text"])
        cands: list[int] = []
        for tok in qt.split():
            if tok.isdigit() and tok.lstrip("0") in by_hn:
                cands += by_hn[tok.lstrip("0")]
        if not cands:
            out.append({"id": r["id"], "abstain": True})
            continue
        best = max(cands[:4000], key=lambda i: fuzz.token_set_ratio(qt, text_of(i)))
        out.append({"id": r["id"], "lat": g.addr[best][12], "lon": g.addr[best][13],
                    "city": g.addr[best][8]})  # fmt: skip
    return out


def baseline_tahdeed(rows: list[dict], db: str, model: str) -> list[dict]:
    """The reference system. Hole rows are resolved with the truth record removed from the index."""
    from .resolve import candidate_city
    from .service import load_resolver

    rs = load_resolver(db=Path(db), model=Path(model), strict=True)
    g = rs.g
    by_osm_a = {a[14]: i for i, a in enumerate(g.addr)}
    by_osm_p = {p[10]: i for i, p in enumerate(g.pois)}
    out = []
    for r in rows:
        ha = hp = frozenset()
        if r["hole"] and r["truth_ref"]:
            kind, osm = r["truth_ref"].split("/", 1)
            if kind == "addr" and osm in by_osm_a:
                ha = frozenset({by_osm_a[osm]})
            elif kind == "poi" and osm in by_osm_p:
                hp = frozenset({by_osm_p[osm]})
        res = rs.resolve(r["text"], ha, hp)
        b = res.best
        if b is None:
            out.append({"id": r["id"], "abstain": True})
            continue
        out.append({
            "id": r["id"], "lat": b.lat, "lon": b.lon, "abstain": res.status != "resolved",
            "confidence": round(float(b.p50), 4), "city": candidate_city(g, b),
        })  # fmt: skip
    return out


def baseline_nominatim(rows: list[dict], limit: int, cache: Path | None = None) -> list[dict]:
    """Public Nominatim, within its usage policy: <=1 request/s, identifying User-Agent, a small
    deterministic sample, cached so a re-run issues no new requests. Never ground truth.

    Hole rows are skipped (a global geocoder cannot have the record removed)."""
    import urllib.parse
    import urllib.request

    cache_d: dict = json.loads(cache.read_text()) if cache and cache.exists() else {}
    out, done = [], 0
    for r in rows:
        if r["hole"] or done >= limit:
            continue  # (sampling is done by the caller)
        key = r["id"]
        if key not in cache_d:
            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                {"q": r["text"], "format": "jsonv2", "limit": 1, "countrycodes": "ae"}
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "tahdeed-bench/1.0 (+https://github.com/hudasol/tahdeed)"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                cache_d[key] = json.load(resp)
            time.sleep(1.2)
            if cache:
                cache.write_text(json.dumps(cache_d))
        data = cache_d[key]
        done += 1
        if data:
            out.append({"id": key, "lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])})
        else:
            out.append({"id": key, "abstain": True})
    return out


# ----------------------------------------------------------------------------- CLI


def _write_preds(preds: list[dict], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for p in preds:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tahdeed bench", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="export the datasets from the gazetteer")
    b.add_argument("--db", default="data/gazetteer.sqlite")
    b.add_argument("--out", default=str(DATA))
    bl = sub.add_parser("baseline", help="run a baseline and write a prediction file")
    bl.add_argument("system", choices=["naive", "tahdeed", "nominatim"])
    bl.add_argument("--set", action="append", default=None, help="dataset name (repeatable)")
    bl.add_argument("--data", default=str(DATA))
    bl.add_argument("--db", default="data/gazetteer.sqlite")
    bl.add_argument("--model", default="data/models/ranker.npz")
    bl.add_argument("--limit", type=int, default=120, help="nominatim: queries per set")
    bl.add_argument("--out", required=True)
    s = sub.add_parser("score", help="score a prediction file")
    s.add_argument("predictions")
    s.add_argument("--data", default=str(DATA))
    s.add_argument("--set", action="append", default=None)
    s.add_argument("--json", default=None)
    r = sub.add_parser("report", help="render docs/BENCH_REPORT.md from bench/results/*.json")
    r.add_argument("--results", default=str(RESULTS))
    r.add_argument("--data", default=str(DATA))
    r.add_argument("--out", default=str(ROOT / "docs" / "BENCH_REPORT.md"))
    a = ap.parse_args(argv)

    if a.cmd == "build":
        build(a.db, Path(a.out))
    elif a.cmd == "baseline":
        rows = load_rows(Path(a.data), a.set)
        if a.system == "naive":
            preds = baseline_naive([r for r in rows if r["kind"] == "addr"], a.db)
        elif a.system == "tahdeed":
            preds = baseline_tahdeed(rows, a.db, a.model)
        else:
            preds = []
            for name in sorted({r["set"] for r in rows}):
                allr = [r for r in rows if r["set"] == name and not r["hole"]]
                sample = allr[:: max(1, len(allr) // a.limit)][: a.limit]  # even stride
                cache = Path(a.out).with_suffix(".cache.json")
                preds += baseline_nominatim(sample, a.limit, cache)
        _write_preds(preds, a.out)
        print(f"wrote {len(preds)} predictions to {a.out}")
    elif a.cmd == "score":
        try:
            res = score(a.predictions, Path(a.data), a.set)
        except ValueError as ex:
            print(f"error: {ex}", file=sys.stderr)
            return 2
        print_score(res)
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    else:
        from .bench_report import render

        Path(a.out).write_text(render(Path(a.results), Path(a.data)), encoding="utf-8")
        print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
