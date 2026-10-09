"""Collect candidate samples, fit the ranker heads, calibrate, and pick the operating point."""

from __future__ import annotations

import multiprocessing as mp
import os
import time
from dataclasses import dataclass

# libgomp thread pools deadlock in forked workers: keep OpenMP single-threaded (set pre-sklearn)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from .calibrate import (
    GBMRanker,
    Policy,
    empirical_radii,
    featurize,
    tier_correct,
    truth_of,
)
from .gazetteer import Gazetteer
from .geo import haversine_m
from .noise import Query, make_address_queries, make_poi_queries
from .resolve import FINE_TIERS, Resolver

# ----------------------------------------------------------------------------- workers

_G: Gazetteer | None = None
_R: Resolver | None = None


def _init_worker(g: Gazetteer, ranker, radii) -> None:
    global _G, _R
    _G = g
    _R = Resolver(g, ranker=ranker, radii=radii)


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


def _pool(g, ranker, radii, workers):
    ctx = mp.get_context("fork")
    return ctx.Pool(workers, initializer=_init_worker, initargs=(g, ranker, radii))


def run_pool(fn, queries, g, ranker=None, radii=None, workers=2):
    if workers <= 1:
        _init_worker(g, ranker, radii)
        return [fn(q) for q in queries]
    with _pool(g, ranker, radii, workers) as p:
        return p.map(fn, queries, chunksize=64)


# ----------------------------------------------------------------------------- fitting


@dataclass
class TrainReport:
    n_train_queries: int
    n_calib_queries: int
    n_train_rows: int
    tau: float
    radii: dict[str, float]
    seconds: float


def build_queries(g: Gazetteer, n_addr: int, n_poi: int, split: str, seed: int, hole_rate: float):
    qs = make_address_queries(g, n_addr, split, seed=seed, hole_rate=hole_rate)
    qs += make_poi_queries(g, n_poi, split, seed=seed)
    return qs


def _gbm() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.08,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        random_state=0,
    )


def train(
    g: Gazetteer,
    n_train: int = 30000,
    n_calib: int = 12000,
    seed: int = 0,
    workers: int = 2,
    verbose: bool = True,
) -> tuple[GBMRanker, TrainReport]:
    t0 = time.time()
    from .calibrate import HeuristicRanker  # noqa: F401  (documented baseline, see evaluate)

    tr = build_queries(g, n_train, max(500, n_train // 20), "train", seed, hole_rate=0.15)
    ca = build_queries(g, n_calib, max(300, n_calib // 20), "calib", seed + 1, hole_rate=0.15)
    if verbose:
        print(f"train queries {len(tr)}, calibration queries {len(ca)}")

    rows = run_pool(_collect_one, tr, g, workers=workers)
    flat = [r for rs in rows for r in rs]
    X = np.array([r[1] for r in flat])
    y50 = np.array([r[3] for r in flat])
    yv = np.array([r[4] for r in flat])
    fine_mask = np.array([r[0] in FINE_TIERS for r in flat])
    if verbose:
        print(
            f"train rows {len(flat)} (fine {int(fine_mask.sum())}), collected in {time.time() - t0:.0f}s"
        )

    m50 = _gbm().fit(X[fine_mask], y50[fine_mask])
    mv = _gbm().fit(X, yv)

    rows_c = run_pool(_collect_one, ca, g, workers=workers)
    flat_c = [r for rs in rows_c for r in rs]
    Xc = np.array([r[1] for r in flat_c])
    y50c = np.array([r[3] for r in flat_c])
    yvc = np.array([r[4] for r in flat_c])
    fine_c = np.array([r[0] in FINE_TIERS for r in flat_c])
    raw50 = m50.predict_proba(Xc[fine_c])[:, 1]
    rawv = mv.predict_proba(Xc)[:, 1]
    iso50 = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw50, y50c[fine_c])
    isov = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(rawv, yvc)

    ranker = GBMRanker(model50=m50, iso50=iso50, model_valid=mv, iso_valid=isov)

    # operating point + radii from a decision-level pass over the calibration queries
    ev = run_pool(_eval_one, ca, g, ranker=ranker, workers=workers)
    tau = _choose_tau(ev)
    ranker.policy = Policy(tau=tau)
    ev2 = run_pool(_eval_one, ca, g, ranker=ranker, workers=workers)
    # Radius = spatial extent *given the right place was found* (correct at its tier); whether
    # it is the right place is what p_valid reports. 90th percentile of distance, per tier.
    errs: dict[str, list[float]] = {}
    for e in ev2:
        if e.get("tier") and e["status"] == "approximate" and e.get("correct"):
            errs.setdefault(e["tier"], []).append(e["dist"])
    radii = empirical_radii(errs)
    ranker.radii = radii
    rep = TrainReport(len(tr), len(ca), len(flat), tau, radii, time.time() - t0)
    if verbose:
        print(f"tau={tau:.3f} radii(90%)={ {k: round(v) for k, v in radii.items()} }")
        print(f"done in {rep.seconds:.0f}s")
    return ranker, rep


def _choose_tau(ev: list[dict], target_precision: float = 0.95) -> float:
    """Smallest tau whose resolved set has precision >= target (correct = within 50 m)."""
    scored = [
        (e["p50"], e["within50"])
        for e in ev
        if e.get("p50") is not None and e.get("tier") in FINE_TIERS
    ]
    if not scored:
        return 0.9
    best = 0.97
    for tau in np.arange(0.50, 0.995, 0.01):
        sel = [ok for p, ok in scored if p >= tau]
        if len(sel) >= 100 and sum(sel) / len(sel) >= target_precision:
            best = float(tau)
            break
    return best
