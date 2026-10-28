"""Scientific studies on top of the evaluation harness: generator gap, ablations, baselines.

Every comparison is paired (same queries) and reported with a bootstrap interval of the
difference, so a gap smaller than its interval is not claimed as a gain.
"""

from __future__ import annotations

import copy
import json
import platform
import sys
from collections import defaultdict

import numpy as np

from .calibrate import HeuristicRanker
from .evaluate import SPLIT, ece, summarize
from .gazetteer import Gazetteer
from .geo import haversine_m
from .model_io import Isotonic, NumpyRanker
from .noise import Query, make_address_queries
from .noise2 import make_address_queries_v2, make_landmark_queries
from .parallel import _eval_one, run_pool
from .resolve import Flags


def environment() -> dict:
    import rapidfuzz

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "rapidfuzz": rapidfuzz.__version__,
    }


def paired_diff(a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean(a - b) with a 95% paired bootstrap interval."""
    d = a.astype(float) - b.astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    m = d[idx].mean(axis=1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"diff": float(d.mean()), "ci95": [float(lo), float(hi)],
            "significant": bool(lo > 0 or hi < 0)}  # fmt: skip


def top1(ev: list[dict]) -> np.ndarray:
    return np.array([float(bool(e.get("within50"))) for e in ev])


def resolved_ok(ev: list[dict]) -> np.ndarray:
    return np.array([float(e["status"] == "resolved" and bool(e.get("within50"))) for e in ev])


def brief(ev: list[dict]) -> dict:
    res = [e for e in ev if e["status"] == "resolved"]
    fine = [e for e in ev if e.get("fine_p50") is not None]
    out = {
        "n": len(ev),
        "forced_top1_50m": float(top1(ev).mean()),
        "resolved_share": len(res) / len(ev),
        "resolved_precision": float(np.mean([bool(e.get("within50")) for e in res]))
        if res
        else None,
        "wrong_confident": int(sum(not e.get("within50") for e in res)),
    }
    if fine:
        out["ece_p50"] = ece(
            np.array([e["fine_p50"] for e in fine]),
            np.array([float(e["fine_within50"]) for e in fine]),
        )
    return out


# ----------------------------------------------------------------------------- baselines


def gazetteer_docs(g: Gazetteer, include_pois: bool = False) -> tuple[list[str], list[tuple]]:
    """One text per gazetteer record (address strings first, then POIs when asked) and, per record,
    ``(lat, lon, city_key, osm_ref)`` with ``osm_ref`` in the benchmark's ``addr/<osm>`` form."""
    docs = [
        " ".join(x for x in (a[1], a[3], a[2], a[5], a[4], a[10], a[9]) if x).lower()
        for a in g.addr
    ]
    meta = [(a[12], a[13], a[8], f"addr/{a[14]}") for a in g.addr]
    if include_pois:
        from .geo import CITY_BY_KEY

        for p in g.pois:
            c = CITY_BY_KEY.get(p[6])
            docs.append(
                " ".join(
                    x
                    for x in (p[1], p[3], p[2], p[7], p[5], c.en if c else "", c.ar if c else "")
                    if x
                ).lower()
            )
            meta.append((p[8], p[9], p[6], f"poi/{p[10]}"))
    return docs, meta


class TfidfBaseline:
    """Character 3-4-gram TF-IDF nearest neighbour over address strings (no parser, no numbers).

    With ``include_pois`` the POI records are indexed too (used by the benchmark baselines)."""

    def __init__(self, g: Gazetteer, include_pois: bool = False) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.g = g
        docs, self.meta = gazetteer_docs(g, include_pois)
        self.vec = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 4), min_df=2, dtype=np.float32
        )
        self.X = self.vec.fit_transform(docs).T.tocsr()  # (features, docs)

    def scores(self, text: str) -> np.ndarray:
        from .normalize import normalize_text

        v = self.vec.transform([normalize_text(text)])
        return (v @ self.X).toarray().ravel()

    def predict(self, q: Query) -> tuple[float, float]:
        i = int(np.argmax(self.scores(q.text)))
        return float(self.meta[i][0]), float(self.meta[i][1])


def tfidf_outcomes(base: TfidfBaseline, queries: list[Query]) -> np.ndarray:
    out = []
    for q in queries:
        lat, lon = base.predict(q)
        out.append(float(haversine_m(lat, lon, q.lat, q.lon) <= 50))
    return np.array(out)


# ----------------------------------------------------------------------------- studies


def _uncalibrated(r: NumpyRanker) -> NumpyRanker:
    """Same trees, isotonic calibration replaced by the identity (raw GBM probabilities)."""
    r2 = copy.copy(r)
    ident = Isotonic(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    r2.heads = {k: (f, ident) for k, (f, _) in r.heads.items()}
    r2.name = "gbm (uncalibrated)"
    return r2


def _within(ev: list[dict], m: float) -> float:
    return float(np.mean([e.get("dist") is not None and e["dist"] <= m for e in ev]))


def landmark_study(g: Gazetteer, ranker, n: int, seed: int, workers: int = 2) -> dict:
    """Landmark-relative queries ("near X, city"): does the landmark tier earn its keep?"""
    lm_q = make_landmark_queries(g, min(n, 1500), SPLIT, seed=seed)
    on = run_pool(_eval_one, lm_q, g, ranker=ranker, radii=ranker.radii, workers=workers)
    off = run_pool(_eval_one, lm_q, g, ranker=ranker, radii=ranker.radii, workers=workers,
                   flags=Flags(landmark=False))  # fmt: skip
    return {
        "n": len(lm_q),
        "with_landmark_tier": brief(on),
        "without": brief(off),
        "top1_within_200m": _within(on, 200),
        "top1_within_200m_without": _within(off, 200),
    }


def run_studies(
    g: Gazetteer,
    ranker: NumpyRanker,
    ranker_h0: NumpyRanker | None = None,
    n: int = 2500,
    seed: int = 31,
    workers: int = 2,
    baseline: bool = True,
) -> dict:
    res: dict = {"env": environment(), "split": SPLIT, "seed": seed}

    # 1. generator gap ----------------------------------------------------------------------
    q1 = make_address_queries(g, n, SPLIT, seed=seed)
    q2 = make_address_queries_v2(g, n, SPLIT, seed=seed)
    e1 = run_pool(_eval_one, q1, g, ranker=ranker, radii=ranker.radii, workers=workers)
    e2 = run_pool(_eval_one, q2, g, ranker=ranker, radii=ranker.radii, workers=workers)
    res["generator_gap"] = {
        "v1_english_perturbed": summarize(e1, q1),
        "v2_from_arabic": summarize(e2, q2),
    }
    by_style = defaultdict(list)
    for e, q in zip(e2, q2, strict=True):
        by_style[next(t for t in q.noise if t.startswith("style_"))].append(e)
    res["v2_by_style"] = {k: brief(v) for k, v in by_style.items()}

    # 2. ablations on a mixed benchmark (v1 + v2, 30% holes) ------------------------------------
    mix_q = make_address_queries(
        g, n, SPLIT, seed=seed + 1, hole_rate=0.3
    ) + make_address_queries_v2(g, n, SPLIT, seed=seed + 1, hole_rate=0.3)
    configs: dict[str, tuple] = {
        "full system": (ranker, Flags()),
        "- consonant-class matching (coarse)": (ranker, Flags(coarse=False)),
        "- sibling street keys": (ranker, Flags(siblings=False)),
        "- full-name fuzzy spans": (ranker, Flags(fuzzy=False)),
        "- DP span selection (greedy)": (ranker, Flags(dp=False)),
        "- interpolation": (ranker, Flags(interp=False)),
        "- all three recall aids": (ranker, Flags(coarse=False, siblings=False, fuzzy=False)),
        "- isotonic calibration": (_uncalibrated(ranker), Flags()),
        "hand-set confidence instead of GBM": (HeuristicRanker(), Flags()),
    }
    if ranker_h0 is not None:
        configs["trained without hole examples"] = (ranker_h0, Flags())
    outs: dict[str, list[dict]] = {}
    for name, (rk, fl) in configs.items():
        outs[name] = run_pool(_eval_one, mix_q, g, ranker=rk, radii=getattr(rk, "radii", None),
                              workers=workers, flags=fl)  # fmt: skip
    base_t = top1(outs["full system"])
    base_r = resolved_ok(outs["full system"])
    abl = {}
    for name, ev in outs.items():
        row = brief(ev)
        if name != "full system":
            row["top1_vs_full"] = paired_diff(top1(ev), base_t)
            row["resolved_correct_vs_full"] = paired_diff(resolved_ok(ev), base_r)
        abl[name] = row
    res["ablations"] = {"n": len(mix_q), "rows": abl}

    res["landmark"] = landmark_study(g, ranker, n, seed, workers)

    # 3. baselines on the same mix ------------------------------------------------------------
    if baseline:
        tb = TfidfBaseline(g)
        t_out = tfidf_outcomes(tb, mix_q)
        res["baseline_tfidf_char34"] = {
            "forced_top1_50m": float(t_out.mean()),
            "vs_full": paired_diff(t_out, base_t),
        }
    return res


def main(g: Gazetteer, ranker, ranker_h0, out: str, n: int) -> dict:
    res = run_studies(g, ranker, ranker_h0, n=n)
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    return res
