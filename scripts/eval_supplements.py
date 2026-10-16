"""Size Overture Places and GeoNames as Dubai POI supplements against the OSM gazetteer (T4).

    python -I scripts/eval_supplements.py --db data/gazetteer.sqlite \
        --overture supp/overture_dubai.jsonl --geonames supp/geonames/AE.txt \
        --out docs/supplements_dubai.json

MIXED TRUTH: OSM, Overture and GeoNames are each someone's claim. Agreement is not accuracy, and a
place found only in a supplement has no independent truth here. "Same name" = a shared tahdeed
name key (``keys_of``). Prints and writes aggregate counts only.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict

import numpy as np

from tahdeed.crosscity import rate
from tahdeed.gazetteer import Gazetteer, keys_of
from tahdeed.noise import split_of

BBOX = (54.9, 24.75, 55.65, 25.45)  # lon/lat W,S,E,N
PERMISSIVE = {"CDLA-Permissive-2.0", "Apache-2.0", "CC0-1.0"}
CELL = 0.005  # about 500 m


def _in(lat: float, lon: float) -> bool:
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def _m(lat1, lon1, lat2, lon2) -> float:
    k = 111_320.0
    return math.hypot((lon2 - lon1) * k * math.cos(math.radians(lat1)), (lat2 - lat1) * k)


class KeyIndex:
    """Name key -> points, with a coarse grid for radius queries."""

    def __init__(self) -> None:
        self.by: dict[tuple[str, int, int], list[tuple[float, float]]] = defaultdict(list)

    def add(self, keys: set[str], lat: float, lon: float) -> None:
        c = (int(lat // CELL), int(lon // CELL))
        for k in keys:
            self.by[(k, *c)].append((lat, lon))

    def nearest(self, keys: set[str], lat: float, lon: float, r: int = 1) -> float:
        ci, cj = int(lat // CELL), int(lon // CELL)
        best = math.inf
        for k in keys:
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    for la, lo in self.by.get((k, ci + di, cj + dj), ()):
                        best = min(best, _m(lat, lon, la, lo))
        return best


def _licences(sources: list[dict]) -> set[str]:
    out = set()
    for s in sources or []:
        lic = s.get("license")
        if lic:
            out.add(lic)
        else:  # older schema without the field: map by dataset (Overture attribution page)
            ds = (s.get("dataset") or "").lower()
            out.add("Apache-2.0" if "foursquare" in ds else "CC0-1.0" if "alltheplaces" in ds
                    else "CDLA-Permissive-2.0" if ds else "unknown")  # fmt: skip
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--overture", required=True)
    ap.add_argument("--geonames", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    g = Gazetteer.load(a.db)

    osm = KeyIndex()
    truth_pool = []
    for p in g.pois:
        if not (p[3] or p[2]) or not _in(p[8], p[9]):
            continue
        ks = keys_of(p[3], p[2])
        osm.add(ks, p[8], p[9])
        if p[6] == "dubai" and p[5] and split_of(f"poi|{p[6]}|{p[5]}") == "dev":
            truth_pool.append((ks, p[8], p[9]))

    ov = KeyIndex()
    ov_rows = []
    lic_count: Counter = Counter()
    n_ov = n_perm = 0
    with open(a.overture, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            n_ov += 1
            lics = _licences(d.get("sources"))
            lic_count.update(lics)
            if lics and lics <= PERMISSIVE:
                n_perm += 1
            ks = keys_of(d.get("name"), d.get("name_en"), d.get("name_ar"))
            if not ks:
                continue
            ov.add(ks, d["lat"], d["lon"])
            ov_rows.append((ks, d["lat"], d["lon"], d.get("confidence") or 0.0))

    # T4.2/T4.3: OSM truth pool matched in Overture within 100 m
    dists = [ov.nearest(ks, la, lo) for ks, la, lo in truth_pool]
    matched = [x for x in dists if x <= 100]
    # T4.4: confident Overture places without an OSM POI of the same key within 500 m
    conf = [r for r in ov_rows if r[3] >= 0.7]
    novel = sum(1 for ks, la, lo, _ in conf if osm.nearest(ks, la, lo) > 500)

    # T4.5: GeoNames feature class S in the bbox
    gn_rows = []
    with open(a.geonames, encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 8 or f[6] != "S":
                continue
            lat, lon = float(f[4]), float(f[5])
            if _in(lat, lon):
                gn_rows.append((keys_of(f[1], f[2]), lat, lon))
    gn_novel = sum(1 for ks, la, lo in gn_rows if ks and osm.nearest(ks, la, lo) > 500)

    res = {
        "caveat": "mixed truth: agreement between sources is not accuracy",
        "bbox_lon_lat": BBOX,
        "overture": {
            "rows_in_bbox": n_ov,
            "rows_only_permissive_licences": rate(n_perm, n_ov),
            "licence_counts": dict(lic_count),
            "named_rows": len(ov_rows),
            "confidence_ge_0_7": len(conf),
            "confident_without_osm_same_key_500m": rate(novel, len(conf)),
        },
        "osm_dev_dubai_poi_pool": {
            "n": len(truth_pool),
            "overture_same_key_within_100m": rate(len(matched), len(truth_pool)),
            "median_m_of_matched": float(np.median(matched)) if matched else None,
        },
        "geonames": {
            "class_S_rows_in_bbox": len(gn_rows),
            "without_osm_same_key_500m": gn_novel,
        },
    }
    print(json.dumps(res, indent=1))
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
