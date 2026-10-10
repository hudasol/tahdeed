"""Evaluation harness: held-out districts, coverage-hole test, Dubai POI test, baselines.

Every number in docs/EVALUATION.md is produced by ``tahdeed eval``. Test queries come from
districts the models never saw (see :func:`tahdeed.noise.split_of`).
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict

import numpy as np
from rapidfuzz import fuzz

from .calibrate import GBMRanker, HeuristicRanker
from .gazetteer import Gazetteer
from .geo import haversine_m
from .noise import Query, make_address_queries, make_poi_queries
from .parallel import _eval_one, run_pool
from .resolve import FINE_TIERS, Resolver

SPLIT = os.environ.get(
    "TAHDEED_SPLIT", "dev"
)  # "sealed" only for the final report (docs/PREDICTIONS.md)

# ----------------------------------------------------------------------------- metrics


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error (equal-width bins)."""
    if len(p) == 0:
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    tot = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                        "mean_p": float(p[m].mean()), "frac_correct": float(y[m].mean())})  # fmt: skip
    return out


def bootstrap_ci(x: np.ndarray, n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap interval of the mean of a 0/1 (or real) vector."""
    if len(x) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(ev: list[dict], queries: list[Query]) -> dict:
    n = len(ev)
    status = defaultdict(int)
    for e in ev:
        status[e["status"]] += 1
    resolved = [e for e in ev if e["status"] == "resolved"]
    approx = [e for e in ev if e["status"] == "approximate"]
    ambiguous = [e for e in ev if e["status"] == "ambiguous"]
    answered = [e for e in ev if e.get("tier")]

    def frac(xs, key):
        return float(np.mean([bool(x.get(key)) for x in xs])) if xs else float("nan")

    out: dict = {
        "n": n,
        "status": {k: v / n for k, v in status.items()},
        "resolved_precision_50m": frac(resolved, "within50"),
        "resolved_precision_200m": frac(resolved, "within200"),
        "resolved_coverage": len(resolved) / n,
        "forced_top1_50m": frac(answered, "within50") * len(answered) / n if n else float("nan"),
        "forced_top1_200m": frac(answered, "within200") * len(answered) / n if n else float("nan"),
        "forced_top1_1km": frac(answered, "within1k") * len(answered) / n if n else float("nan"),
        "approx_tier_correct": frac(approx, "correct"),
        "approx_within_radius": frac(approx, "within_radius"),
        "ambiguous_top_within_50m": frac(ambiguous, "within50"),
        "latency_ms_p50": float(np.percentile([e["ms"] for e in ev], 50)),
        "latency_ms_p95": float(np.percentile([e["ms"] for e in ev], 95)),
        "mean_asks": float(np.mean([e["asks"] for e in ev])),
    }
    if resolved:
        out["resolved_precision_50m_ci95"] = bootstrap_ci(
            np.array([float(bool(e.get("within50"))) for e in resolved])
        )
    out["forced_top1_50m_ci95"] = bootstrap_ci(
        np.array([float(bool(e.get("within50"))) for e in ev])
    )
    for head, key, thr in (("p200", "p200", "within200"), ("p1k", "p1k", "within1k")):
        pp = [(e[key], float(bool(e[thr]))) for e in answered if e.get(key) is not None]
        if pp:
            out[f"ece_{head}"] = ece(np.array([a for a, _ in pp]), np.array([b for _, b in pp]))
    fine = [e for e in ev if e.get("fine_p50") is not None]
    if fine:
        p = np.array([e["fine_p50"] for e in fine])
        y = np.array([float(e["fine_within50"]) for e in fine])
        out["ece_p50"] = ece(p, y)
        out["reliability_p50"] = reliability(p, y)
        # risk-coverage: answer the most confident first
        order = np.argsort(-p)
        cum = np.cumsum(y[order]) / np.arange(1, len(y) + 1)
        pts = []
        for cov in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            k = max(1, int(cov * len(y)))
            pts.append({"coverage": cov, "precision_50m": float(cum[k - 1]), "min_p": float(p[order][k - 1])})  # fmt: skip
        out["risk_coverage"] = pts
    pv = [e for e in answered if e.get("p_valid") is not None]
    if pv:
        p = np.array([e["p_valid"] for e in pv])
        y = np.array([float(e["correct"]) for e in pv])
        out["ece_p_valid"] = ece(p, y)
    # by slice / noise tag
    by_slice: dict[str, list[dict]] = defaultdict(list)
    by_noise: dict[str, list[dict]] = defaultdict(list)
    for e, q in zip(ev, queries, strict=True):
        by_slice[q.slice].append(e)
        for t in set(q.noise):
            by_noise[t].append(e)

    def brief(xs):
        r = [e for e in xs if e["status"] == "resolved"]
        return {
            "n": len(xs),
            "resolved": len(r) / len(xs),
            "resolved_precision_50m": frac(r, "within50"),
            "top1_50m": float(np.mean([bool(e.get("within50")) for e in xs])),
            "top1_1km": float(np.mean([bool(e.get("within1k")) for e in xs])),
        }

    out["by_slice"] = {k: brief(v) for k, v in by_slice.items()}
    out["by_noise"] = {k: brief(v) for k, v in sorted(by_noise.items()) if len(v) >= 30}
    return out


# ----------------------------------------------------------------------------- baselines


def naive_fuzzy(g: Gazetteer, queries: list[Query]) -> dict:
    """Baseline: best token-set fuzzy match of the whole query against address strings.

    Candidate set is limited to addresses sharing a house-number token with the query (a
    generous shortcut for the baseline); the query is scored on the raw text.
    """
    by_hn: dict[str, list[int]] = defaultdict(list)
    for i, hn in enumerate(g.addr_hn):
        by_hn[hn].append(i)
    texts: dict[int, str] = {}

    def text_of(i: int) -> str:
        if i not in texts:
            a = g.addr[i]
            texts[i] = " ".join(x for x in (a[1], a[3], a[2], a[5], a[4], a[10], a[9]) if x).lower()
        return texts[i]

    from .normalize import normalize_text

    d50 = d200 = d1k = answered = 0
    t0 = time.perf_counter()
    for q in queries:
        qt = normalize_text(q.text)
        cands: list[int] = []
        for tok in qt.split():
            if tok.isdigit() and tok.lstrip("0") in by_hn:
                cands += by_hn[tok.lstrip("0")]
        if not cands:
            continue
        best = max(cands[:4000], key=lambda i: fuzz.token_set_ratio(qt, text_of(i)))
        answered += 1
        d = haversine_m(g.addr[best][12], g.addr[best][13], q.lat, q.lon)
        d50 += d <= 50
        d200 += d <= 200
        d1k += d <= 1000
    n = len(queries)
    return {
        "n": n,
        "answered": answered / n,
        "top1_50m": d50 / n,
        "top1_200m": d200 / n,
        "top1_1km": d1k / n,
        "ms_per_query": (time.perf_counter() - t0) * 1000 / n,
    }


def nominatim_sample(queries: list[Query], limit: int = 200) -> dict:
    """Optional: public Nominatim (1 req/s, respects its usage policy). Skipped if unreachable."""
    import urllib.parse
    import urllib.request

    sample = queries[:limit]
    d50 = d1k = answered = done = 0
    for q in sample:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q.text, "format": "json", "limit": 1, "countrycodes": "ae"}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "tahdeed-eval/1.0 (research)"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                data = json.load(r)
        except Exception as ex:  # network blocked etc.
            if done == 0:
                return {"skipped": f"{type(ex).__name__}: {ex}"}
            break
        done += 1
        if data:
            answered += 1
            d = haversine_m(float(data[0]["lat"]), float(data[0]["lon"]), q.lat, q.lon)
            d50 += d <= 50
            d1k += d <= 1000
        time.sleep(1.1)
    return {"n": done, "answered": answered / max(done, 1), "top1_50m": d50 / max(done, 1),
            "top1_1km": d1k / max(done, 1)}  # fmt: skip


def hole_sensitivity(g, ranker, rates=(0.0, 0.15, 0.3, 0.5, 1.0), n=1500, seed=21, workers=2):
    """How do precision / calibration move when the share of absent addresses changes?"""
    out = {}
    for r in rates:
        qs = make_address_queries(g, n, SPLIT, seed=seed, hole_rate=r)
        ev = run_pool(_eval_one, qs, g, ranker=ranker, radii=ranker.radii, workers=workers)
        sm = summarize(ev, qs)
        out[str(r)] = {k: sm.get(k) for k in ("resolved_coverage", "resolved_precision_50m",
                                              "forced_top1_50m", "ece_p50", "ece_p1k")}  # fmt: skip
    return out


# ----------------------------------------------------------------------------- driver


def evaluate(
    g: Gazetteer,
    ranker: GBMRanker,
    n_addr: int = 6000,
    n_hole: int = 2500,
    n_poi: int = 1500,
    n_baseline: int = 1000,
    nominatim: int = 0,
    seed: int = 7,
    workers: int = 2,
) -> dict:
    addr_q = make_address_queries(g, n_addr, SPLIT, seed=seed)
    hole_q = make_address_queries(g, n_hole, SPLIT, seed=seed + 1, hole_rate=1.0)
    poi_q = make_poi_queries(g, n_poi, SPLIT, seed=seed)
    res: dict = {"seed": seed, "gazetteer": g.stats(), "meta": g.meta}

    ev = run_pool(_eval_one, addr_q, g, ranker=ranker, radii=ranker.radii, workers=workers)
    res["abu_dhabi_structured"] = summarize(ev, addr_q)
    ev = run_pool(_eval_one, hole_q, g, ranker=ranker, radii=ranker.radii, workers=workers)
    res["coverage_hole"] = summarize(ev, hole_q)
    ev = run_pool(_eval_one, poi_q, g, ranker=ranker, radii=ranker.radii, workers=workers)
    res["dubai_poi"] = summarize(ev, poi_q)

    res["hole_sensitivity"] = hole_sensitivity(g, ranker, workers=workers)
    res["split"] = SPLIT
    heur = HeuristicRanker()
    ev = run_pool(_eval_one, addr_q[: n_baseline * 2], g, ranker=heur, radii=None, workers=workers)
    res["baseline_heuristic_ranker"] = summarize(ev, addr_q[: n_baseline * 2])
    res["baseline_naive_fuzzy"] = naive_fuzzy(g, addr_q[:n_baseline])
    if nominatim:
        res["nominatim_sample"] = nominatim_sample(addr_q[::7], nominatim)
    return res


def to_markdown(res: dict) -> str:
    def row(name, d):
        return (f"| {name} | {d['n']} | {d['resolved_coverage']:.1%} | "
                f"{d['resolved_precision_50m']:.1%} | {d['forced_top1_50m']:.1%} | "
                f"{d['forced_top1_200m']:.1%} | {d['forced_top1_1km']:.1%} | "
                f"{d['latency_ms_p50']:.1f} |")  # fmt: skip

    lines = [
        "| Benchmark | n | resolved | precision@50m (resolved) | top-1 <=50m | <=200m | <=1km "
        "| p50 ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, name in (("abu_dhabi_structured", "Abu Dhabi/Al Ain/Al Dhafra, held-out districts"),
                      ("coverage_hole", "Same, true address removed from index"),
                      ("dubai_poi", "Dubai/Sharjah/Ajman POI (weaker truth)"),
                      ("baseline_heuristic_ranker", "Baseline: hand-set confidence rules")):  # fmt: skip
        if key in res:
            lines.append(row(name, res[key]))
    return "\n".join(lines)


_ = FINE_TIERS, Resolver  # re-exported for convenience
