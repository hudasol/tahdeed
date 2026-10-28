"""POI calibration ablation (Phase 2, T1): which v2.1 change moved Dubai POI calibration?

v2.0 to v2.1 changed four things at once: two candidate features (``name_n_cities``,
``city_share``), the cross-city training mix, candidate diversification across cities, and the
city gate. This driver scores each trained model under three resolver configurations on the dev
split only:

* ``shipped``      diversification on, gate on (the v2.1 default)
* ``gate_off``     diversification on, gate off
* ``v20_flags``    diversification off, gate off (the v2.0 resolver)

For each it records the Dubai/Sharjah/Ajman POI benchmark (same seed and size as ``tahdeed eval``)
with a bootstrap interval for ECE, and, under the shipped flags, the cross-city risk cells and the
standard benchmark at the default gate margin. Predictions: ``docs/PREDICTIONS.md`` (T1).
"""

from __future__ import annotations

import json
import time

import numpy as np

from .evaluate import ece, summarize
from .gazetteer import Gazetteer
from .model_io import load as load_model
from .noise import make_poi_queries
from .parallel import _eval_one, run_pool
from .resolve import Flags

FLAG_SETS = {
    "shipped": Flags(),
    "gate_off": Flags(city_gate=False),
    "v20_flags": Flags(diversify=False, city_gate=False),
}


def ece_ci(p: np.ndarray, y: np.ndarray, n_boot: int = 1000, seed: int = 0) -> list[float]:
    """95% percentile bootstrap interval of ECE (queries resampled with replacement)."""
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        i = rng.integers(0, len(p), len(p))
        vals.append(ece(p[i], y[i]))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def poi_block(ev: list[dict], qs) -> dict:
    sm = summarize(ev, qs)
    fine = [e for e in ev if e.get("fine_p50") is not None]
    p = np.array([e["fine_p50"] for e in fine])
    y = np.array([float(e["fine_within50"]) for e in fine])
    answered = sm["status"].get("resolved", 0.0)
    return {
        "n": sm["n"],
        "status": sm["status"],
        "resolved_coverage": answered,
        "resolved_precision_50m": sm["resolved_precision_50m"],
        "forced_top1_50m": sm["forced_top1_50m"],
        "ece_p50": sm.get("ece_p50"),
        "ece_p50_ci95": ece_ci(p, y) if len(p) else None,
        "n_fine": len(p),
        "mean_p50": float(p.mean()) if len(p) else None,
        "frac_within50": float(y.mean()) if len(y) else None,
        "reliability_p50": sm.get("reliability_p50"),
    }


def run(models: dict[str, str], db: str, out: str, workers: int = 2, n_poi: int = 1500,
        crosscity: bool = True) -> dict:  # fmt: skip
    from .crosscity import run_crosscity

    g = Gazetteer.load(db)
    qs = make_poi_queries(g, n_poi, "dev", seed=7)  # identical to `tahdeed eval` (dev)
    res: dict = {"split": "dev", "gazetteer_sha256": g.sha256, "meta": g.meta,
                 "n_poi": len(qs), "models": {}}  # fmt: skip
    for name, path in models.items():
        t0 = time.time()
        rk = load_model(path, gazetteer_sha256=g.sha256)
        mf = rk.manifest
        entry: dict = {
            "path": path,
            "manifest": {k: mf.get(k) for k in ("crosscity_mix", "crosscity_poi_hole",
                                                 "masked_features", "n_train", "hole_rate")},
            "tau": mf["policy"]["tau"],
            "poi": {},
        }  # fmt: skip
        for fname, fl in FLAG_SETS.items():
            ev = run_pool(_eval_one, qs, g, ranker=rk, radii=rk.radii, workers=workers, flags=fl)
            entry["poi"][fname] = poi_block(ev, qs)
        if crosscity:
            cc = run_crosscity(g, rk, "dev", margins=(0.35,), workers=workers)
            entry["crosscity"] = {
                k: {
                    "risk_E0": v["cells"].get("risk/E0"),
                    "named_unique_E0": v["cells"].get("named_unique/E0"),
                    "poi_E0": v["cells"].get("poi/E0"),
                    "poi_E2": v["cells"].get("poi/E2"),
                    "standard": v["standard"],
                }
                for k, v in cc["configs"].items()
            }
        entry["seconds"] = round(time.time() - t0, 1)
        res["models"][name] = entry
        print(name, {k: round(v["ece_p50"], 3) for k, v in entry["poi"].items()}, flush=True)
        with open(out, "w") as fh:  # written after every model so a partial run is kept
            json.dump(res, fh, indent=1, default=float)
    return res
