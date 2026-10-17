"""Clarification loop measurement (Phase 2, T2): does answering "Which city?" resolve the query?

On the cross-city dev set (the generator and seed of ``crosscity_dev``), every E0 query that the
city gate turned into "Which city?" is resolved again with the true city supplied as the ``city``
hint. Hole strata (the true record hidden) are reported apart: there the right outcome is not to
answer. Predictions: ``docs/PREDICTIONS.md`` (T2).
"""

from __future__ import annotations

import json

from .crosscity import make_crosscity_queries, rate
from .gazetteer import Gazetteer
from .model_io import load as load_model
from .parallel import _clarify_one, run_pool


def summarize(ev: list[dict]) -> dict:
    e2 = {e["pair"]: e["status"] for e in ev if e["evidence"] == "E2"}
    out: dict = {}
    groups = {
        "non_hole": lambda s: not s.endswith("hole"),
        "hole": lambda s: s.endswith("hole"),
    }
    strata = sorted({e["stratum"] for e in ev})
    for s in strata:
        groups[s] = lambda x, s=s: x == s
    for name, keep in groups.items():
        e0 = [e for e in ev if e["evidence"] == "E0" and keep(e["stratum"])]
        asked = [e for e in e0 if e["hinted"] is not None]
        h = [e["hinted"] for e in asked]
        res = [x for x in h if x["status"] == "resolved"]
        same = [e for e in asked if e2.get(e["pair"]) == e["hinted"]["status"]]
        out[name] = {
            "n_e0": len(e0),
            "asked_city": rate(len(asked), len(e0)),
            "hint_resolved": rate(len(res), len(asked)),
            "hint_resolved_within50": rate(sum(1 for x in res if x["within50"]), len(asked)),
            "hint_resolved_beyond50": rate(sum(1 for x in res if not x["within50"]), len(asked)),
            "hint_resolved_wrong_city": rate(sum(1 for x in res if x["wrong_city"]), len(asked)),
            "hint_status": {
                k: sum(1 for x in h if x["status"] == k)
                for k in ("resolved", "approximate", "ambiguous", "unresolved")
            },
            "same_status_as_E2": rate(len(same), len([e for e in asked if e["pair"] in e2])),
        }
    return out


def run(db: str, model: str, out: str, split: str = "dev", workers: int = 2) -> dict:
    if split != "dev":
        raise SystemExit("clarify runs on dev only (sealed sets are not for iteration)")
    g = Gazetteer.load(db)
    rk = load_model(model, gazetteer_sha256=g.sha256)
    qs = make_crosscity_queries(g, split, seed=0)
    ev = run_pool(_clarify_one, qs, g, ranker=rk, radii=rk.radii, workers=workers)
    res = {
        "split": split,
        "gazetteer_sha256": g.sha256,
        "model_arrays_sha256": rk.manifest.get("arrays_sha256"),
        "n_queries": len(qs),
        "groups": summarize(ev),
    }
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    return res
