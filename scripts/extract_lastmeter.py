"""Build the EXPLORATORY last meter sidecar (buildings, entrance vertices, roads) from an OSM extract.

    python scripts/extract_lastmeter.py extract.osm.pbf data/lastmeter.sqlite [--bbox W,S,E,N]

Default bbox: Abu Dhabi emirate (approximate). Output is an ODbL derived database
(© OpenStreetMap contributors); it is built locally and not committed.

* ``buildings``: closed ways tagged ``building=*`` (centroid of the vertices, ring as JSON).
* ``entrances``: nodes tagged ``entrance=*`` or ``door=*``; ``building_id`` is set when the node
  is a vertex of a building outline (the label rule used in ``scripts/eval_lastmeter.py``).
* ``roads``: ways tagged ``highway=*`` (drivable roads and paths), coordinates as JSON.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import osmium

DEFAULT_BBOX = (51.5, 22.6, 56.0, 24.9)  # Abu Dhabi emirate, lon/lat W,S,E,N
HIGHWAYS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "service", "living_street", "pedestrian", "footway", "path", "steps", "motorway_link",
    "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}  # fmt: skip


class Handler(osmium.SimpleHandler):
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        super().__init__()
        self.bbox = bbox
        self.entr: dict[int, tuple[float, float, str]] = {}
        self.entr_building: dict[int, int] = {}
        self.buildings: list[tuple[int, float, float, str]] = []
        self.roads: list[tuple[int, str, str]] = []

    def _in(self, lat: float, lon: float) -> bool:
        w, s, e, n = self.bbox
        return w <= lon <= e and s <= lat <= n

    def node(self, n) -> None:
        t = n.tags
        if ("entrance" in t or "door" in t) and n.location.valid():
            if self._in(n.location.lat, n.location.lon):
                self.entr[n.id] = (n.location.lat, n.location.lon, t.get("entrance") or "door")

    def way(self, w) -> None:
        t = w.tags
        try:
            pts = [(nd.lat, nd.lon) for nd in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(pts) < 2 or not self._in(*pts[0]):
            return
        if "building" in t and len(pts) >= 4 and w.nodes[0].ref == w.nodes[-1].ref:
            lat = sum(p[0] for p in pts[:-1]) / (len(pts) - 1)
            lon = sum(p[1] for p in pts[:-1]) / (len(pts) - 1)
            self.buildings.append(
                (w.id, lat, lon, json.dumps([[round(a, 7), round(b, 7)] for a, b in pts]))
            )
            for nd in w.nodes:
                if nd.ref in self.entr:
                    self.entr_building.setdefault(nd.ref, w.id)
        elif t.get("highway") in HIGHWAYS:
            self.roads.append(
                (w.id, t.get("highway"), json.dumps([[round(a, 7), round(b, 7)] for a, b in pts]))
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("out")
    ap.add_argument("--bbox", default=",".join(map(str, DEFAULT_BBOX)))
    a = ap.parse_args()
    bbox = tuple(float(x) for x in a.bbox.split(","))
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists; refusing to overwrite")
    h = Handler(bbox)
    h.apply_file(a.pbf, locations=True)
    con = sqlite3.connect(out)
    con.executescript(
        "CREATE TABLE buildings(id INTEGER PRIMARY KEY, lat REAL, lon REAL, ring TEXT);"
        "CREATE TABLE entrances(id INTEGER PRIMARY KEY, lat REAL, lon REAL, kind TEXT, building_id INTEGER);"
        "CREATE TABLE roads(id INTEGER PRIMARY KEY, kind TEXT, coords TEXT);"
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
    )
    con.executemany("INSERT INTO buildings VALUES (?,?,?,?)", h.buildings)
    con.executemany(
        "INSERT INTO entrances VALUES (?,?,?,?,?)",
        [(i, la, lo, k, h.entr_building.get(i)) for i, (la, lo, k) in h.entr.items()],
    )
    con.executemany("INSERT INTO roads VALUES (?,?,?)", h.roads)
    meta = {"source": Path(a.pbf).name, "bbox": a.bbox, "license": "ODbL 1.0 (c) OpenStreetMap contributors",
            "exploratory": "yes"}  # fmt: skip
    con.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    con.commit()
    n_lab = sum(1 for v in h.entr_building.values() if v)
    print(json.dumps({"buildings": len(h.buildings), "entrances": len(h.entr),
                      "entrances_on_outline": n_lab, "roads": len(h.roads)}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
