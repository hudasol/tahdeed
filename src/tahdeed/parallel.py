"""Multiprocessing helpers shared by training and evaluation (no scikit-learn needed)."""

from __future__ import annotations

import multiprocessing as mp
import time

from .calibrate import featurize, tier_correct, truth_of
from .gazetteer import Gazetteer
from .geo import haversine_m
from .noise import Query
from .resolve import FINE_TIERS, Resolver

_G: Gazetteer | None = None
_R: Resolver | None = None


def _init_worker(g: Gazetteer, ranker, radii, flags=None) -> None:
    global _G, _R
    _G = g
    _R = Resolver(g, ranker=ranker, radii=radii)
    if flags is not None:
        _R.flags = flags


def _hide(q: Query) -> tuple[frozenset[int], frozenset[int]]:
    if not q.hidden:
        return frozenset(), frozenset()
    if q.truth_kind == "addr":
        return frozenset({q.truth_idx}), frozenset()
    return frozenset(), frozenset({q.truth_idx})


def _collect_one(q: Query):
    """Candidate rows for one query: (tier, features, dist_m, y50, y_valid)."""
    assert _R is not None and _G is not None
    ha, hp = _hide(q)
    res_cands = _R.resolve_candidates(q.text, ha, hp)
    t = truth_of(_G, q)
    rows = []
    for c in res_cands:
        d = haversine_m(c.lat, c.lon, t.lat, t.lon)
        rows.append((c.tier, featurize(c), d, int(d <= 50.0), int(tier_correct(c, t, d))))
    return rows


def _eval_one(q: Query):
    """Decision-level outcome for one query."""
    assert _R is not None and _G is not None
    ha, hp = _hide(q)
    t0 = time.perf_counter()
    res = _R.resolve(q.text, ha, hp)
    ms = (time.perf_counter() - t0) * 1000
    t = truth_of(_G, q)
    b = res.best
    out = {
        "status": res.status,
        "ms": ms,
        "asks": len(res.asks),
    }
    if b is None:
        out.update(tier=None, dist=None, p50=None, p_valid=None, radius=None, correct=False)
        return out
    d = haversine_m(b.lat, b.lon, t.lat, t.lon)
    out.update(
        tier=b.tier,
        dist=d,
        p50=b.p50,
        p_valid=b.p_valid,
        p200=b.p200,
        p1k=b.p1k,
        radius=b.radius_m,
        within_radius=d <= b.radius_m,
        correct=bool(tier_correct(b, t, d)),
        within50=d <= 50.0,
        within200=d <= 200.0,
        within1k=d <= 1000.0,
    )
    # best fine candidate irrespective of status (for calibration / forced-answer metrics)
    fine = [c for c in (res.alternatives + [b]) if c.tier in FINE_TIERS]
    if fine:
        f = max(fine, key=lambda c: c.p50 or 0.0)
        out["fine_p50"] = f.p50
        out["fine_within50"] = haversine_m(f.lat, f.lon, t.lat, t.lon) <= 50.0
    return out


def _pool(g, ranker, radii, workers, flags=None):
    ctx = mp.get_context("fork")
    return ctx.Pool(workers, initializer=_init_worker, initargs=(g, ranker, radii, flags))


def run_pool(fn, queries, g, ranker=None, radii=None, workers=2, flags=None):
    if workers <= 1:
        _init_worker(g, ranker, radii, flags)
        return [fn(q) for q in queries]
    with _pool(g, ranker, radii, workers, flags) as p:
        return p.map(fn, queries, chunksize=64)


def _cc_one(q: Query):
    """Cross-city outcome for one query (see ``crosscity.summarize_cc``)."""
    from .resolve import candidate_city

    assert _R is not None and _G is not None
    ha, hp = _hide(q)
    res = _R.resolve(q.text, ha, hp)
    b = res.best
    t = truth_of(_G, q)
    out = {
        "stratum": q.extra["stratum"],
        "evidence": q.extra["evidence"],
        "status": res.status,
        "truth_majority": q.extra.get("truth_majority"),
        "pair": q.extra["pair"],
        "city_gate": any(a.startswith("Which city?") for a in res.asks),
        "answer_city": None,
        "wrong_city": False,
        "within50": False,
        "p50": None,
        "tier": None,
        "text": q.text,
    }
    if b is not None:
        ac = candidate_city(_G, b)
        out.update(answer_city=ac, wrong_city=bool(ac and ac != t.city), tier=b.tier, p50=b.p50,
                   within50=haversine_m(b.lat, b.lon, t.lat, t.lon) <= 50.0)  # fmt: skip
    return out
