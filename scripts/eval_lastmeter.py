"""EXPLORATORY evaluation of last meter proposals against OSM-mapped entrance vertices (T6).

    python scripts/eval_lastmeter.py data/lastmeter.sqlite --out docs/lastmeter_eval.json

Label rule (fixed before the run): a building is labelled when at least one node tagged
``entrance=*`` or ``door=*`` is a vertex of its outline; the labels are those nodes. Labels are
OSM derived (mapped by OSM contributors), not surveyed. The query point is the outline centroid;
mapped entrances are hidden from the proposers. For each proposer: distance to the nearest
labelled entrance of that building, share within 5, 10 and 20 m (Wilson 95%) and the median.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from tahdeed.crosscity import rate
from tahdeed.lastmeter import LastMeter, _xy

KINDS = ("centroid", "nearest_road_point", "outline_nearest_road", "path_endpoint")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0, help="0 = every labelled building")
    a = ap.parse_args()
    lm = LastMeter(a.db)
    labelled = sorted(lm.entrances)
    if a.limit:
        labelled = labelled[: a.limit]
    dists: dict[str, list[float]] = {k: [] for k in KINDS}
    missing: dict[str, int] = {k: 0 for k in KINDS}
    for bid in labelled:
        blat, blon, _ = lm.buildings[bid]
        ents = lm.entrances[bid]
        res = lm.propose(blat, blon, use_entrances=False)
        if res.building_id != bid:  # centroid fell in, or nearer to, another outline
            for k in KINDS:
                missing[k] += 1
            continue
        for k in KINDS:
            ps = [p for p in res.proposals if p.kind == k]
            if not ps:
                missing[k] += 1
                continue
            p = ps[0]  # path endpoints are sorted by gap to the outline: the first, not the best
            best = min(float(np.hypot(*_xy(p.lat, p.lon, elat, elon))) for elat, elon, _ in ents)
            dists[k].append(best)
    n = len(labelled)
    out: dict = {
        "exploratory": True,
        "labels": "OSM-mapped entrance vertices (entrance=* or door=*) on building outlines; not surveyed",
        "n_labelled_buildings": n,
        "n_entrance_labels": sum(len(lm.entrances[b]) for b in labelled),
        "proposers": {},
    }
    for k in KINDS:
        d = np.array(dists[k])
        out["proposers"][k] = {
            "n_with_proposal": len(d),
            "no_proposal": missing[k],
            "median_m": float(np.median(d)) if len(d) else None,
            **{f"within_{t}m_of_all": rate(int((d <= t).sum()), n) for t in (5, 10, 20)},
        }
    print(json.dumps(out, indent=1, default=float))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
