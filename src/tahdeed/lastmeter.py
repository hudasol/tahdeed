"""EXPLORATORY last meter module: propose where to stop for a resolved building or POI point.

Not part of the resolver and not covered by any headline claim. Given a point (a resolved address
or POI), it finds the OSM building outline that contains it (or the nearest one within
``MAX_BUILDING_M``) and proposes stopping points from open map geometry only:

* ``osm_entrance``          entrance vertices mapped on that outline (``entrance=*``/``door=*``);
* ``outline_nearest_road``  the outline point closest to the nearest drivable road;
* ``path_endpoint``         a footway or service way that ends within ``PATH_END_M`` of the
                            outline, projected onto the outline;
* ``nearest_road_point``    the drivable road point closest to the input (baseline: a geocoder answer);
* ``centroid``              the outline centroid (baseline).

Data: a sidecar SQLite built by ``scripts/extract_lastmeter.py`` from the same OSM extract
(ODbL 1.0, © OpenStreetMap contributors). Evaluation: ``scripts/eval_lastmeter.py``; predictions
T6 in ``docs/PREDICTIONS.md``.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

EXPLORATORY = True
MAX_BUILDING_M = 40.0
ROAD_SEARCH_M = 150.0
PATH_END_M = 15.0
CELL_DEG = 0.004  # grid cell for the spatial index (about 400 m)
PATH_KINDS = {"footway", "service", "path", "pedestrian", "steps", "living_street"}
WALK_ONLY = {"footway", "path", "pedestrian", "steps"}  # not roads a vehicle can stop on


def _xy(lat0: float, lon0: float, lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Local equirectangular metres around (lat0, lon0)."""
    k = 111_320.0
    return (np.asarray(lon) - lon0) * k * math.cos(math.radians(lat0)), (np.asarray(lat) - lat0) * k


def _latlon(lat0: float, lon0: float, x: float, y: float) -> tuple[float, float]:
    k = 111_320.0
    return lat0 + y / k, lon0 + x / (k * math.cos(math.radians(lat0)))


def closest_on_segments(px: float, py: float, ax, ay, bx, by) -> tuple[int, float, float, float]:
    """Index, closest point and distance from (px, py) to the nearest of segments a->b."""
    ax, ay, bx, by = (np.asarray(v, float) for v in (ax, ay, bx, by))
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.where(L2 > 0, ((px - ax) * dx + (py - ay) * dy) / np.where(L2 > 0, L2, 1), 0.0)
    t = np.clip(t, 0.0, 1.0)
    cx, cy = ax + t * dx, ay + t * dy
    d = np.hypot(cx - px, cy - py)
    i = int(np.argmin(d))
    return i, float(cx[i]), float(cy[i]), float(d[i])


def point_in_ring(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> bool:
    inside = False
    n = len(xs)
    j = n - 1
    for i in range(n):
        if (ys[i] > py) != (ys[j] > py):
            x_cross = xs[i] + (py - ys[i]) * (xs[j] - xs[i]) / (ys[j] - ys[i])
            if px < x_cross:
                inside = not inside
        j = i
    return inside


@dataclass
class Proposal:
    kind: str
    lat: float
    lon: float
    dist_from_input_m: float
    note: str = ""
    gap_m: float = 0.0  # path_endpoint: distance from the path end to the outline


@dataclass
class LastMeterResult:
    building_id: int | None
    proposals: list[Proposal] = field(default_factory=list)
    exploratory: bool = True


class LastMeter:
    def __init__(self, db: str | Path) -> None:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.buildings: dict[int, tuple[float, float, list]] = {}
        self.b_grid: dict[tuple[int, int], list[int]] = {}
        for bid, lat, lon, ring in con.execute("SELECT id, lat, lon, ring FROM buildings"):
            self.buildings[bid] = (lat, lon, json.loads(ring))
            self.b_grid.setdefault(self._cell(lat, lon), []).append(bid)
        self.entrances: dict[int, list[tuple[float, float, str]]] = {}
        for bid, lat, lon, kind in con.execute(
            "SELECT building_id, lat, lon, kind FROM entrances WHERE building_id IS NOT NULL"
        ):
            self.entrances.setdefault(bid, []).append((lat, lon, kind))
        self.roads: dict[int, tuple[str, list]] = {}
        self.r_grid: dict[tuple[int, int], set[int]] = {}
        for rid, kind, coords in con.execute("SELECT id, kind, coords FROM roads"):
            cs = json.loads(coords)
            self.roads[rid] = (kind, cs)
            for la, lo in cs:
                self.r_grid.setdefault(self._cell(la, lo), set()).add(rid)
        con.close()

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[int, int]:
        return int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG))

    def _near(self, grid, lat: float, lon: float, r: int = 1):
        ci, cj = self._cell(lat, lon)
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                yield from grid.get((ci + di, cj + dj), ())

    def building_at(self, lat: float, lon: float) -> int | None:
        best, bd = None, MAX_BUILDING_M
        for bid in set(self._near(self.b_grid, lat, lon)):
            blat, blon, ring = self.buildings[bid]
            xs, ys = _xy(lat, lon, [p[0] for p in ring], [p[1] for p in ring])
            if point_in_ring(0.0, 0.0, xs, ys):
                return bid
            _, _, _, d = closest_on_segments(0.0, 0.0, xs[:-1], ys[:-1], xs[1:], ys[1:])
            if d < bd:
                best, bd = bid, d
        return best

    def _road_segments(
        self, lat: float, lon: float, kinds: set[str] | None = None, drivable: bool = False
    ):
        ax, ay, bx, by, rid_of, end = [], [], [], [], [], []
        r = max(1, math.ceil(ROAD_SEARCH_M / (CELL_DEG * 111_320)))
        for rid in set(self._near(self.r_grid, lat, lon, r)):
            kind, cs = self.roads[rid]
            if (kinds is not None and kind not in kinds) or (drivable and kind in WALK_ONLY):
                continue
            xs, ys = _xy(lat, lon, [p[0] for p in cs], [p[1] for p in cs])
            for i in range(len(cs) - 1):
                ax.append(xs[i])
                ay.append(ys[i])
                bx.append(xs[i + 1])
                by.append(ys[i + 1])
                rid_of.append(rid)
            end += [(xs[0], ys[0]), (xs[-1], ys[-1])]
        return ax, ay, bx, by, rid_of, end

    def propose(self, lat: float, lon: float, use_entrances: bool = True) -> LastMeterResult:
        bid = self.building_at(lat, lon)
        out = LastMeterResult(bid)
        ax, ay, bx, by, _, _ = self._road_segments(lat, lon, drivable=True)
        if ax:
            _, cx, cy, d = closest_on_segments(0.0, 0.0, ax, ay, bx, by)
            if d <= ROAD_SEARCH_M:
                rl, ro = _latlon(lat, lon, cx, cy)
                out.proposals.append(Proposal("nearest_road_point", rl, ro, d))
        if bid is None:
            return out
        blat, blon, ring = self.buildings[bid]
        rx, ry = _xy(lat, lon, [p[0] for p in ring], [p[1] for p in ring])
        cxs, cys = _xy(lat, lon, blat, blon)
        out.proposals.append(Proposal("centroid", blat, blon, float(np.hypot(cxs, cys))))
        if use_entrances:
            for elat, elon, kind in self.entrances.get(bid, []):
                ex, ey = _xy(lat, lon, elat, elon)
                out.proposals.insert(
                    0, Proposal("osm_entrance", elat, elon, float(np.hypot(ex, ey)), kind)
                )
        if ax:
            # outline point closest to any road segment: scan outline vertices and road segments
            best = (math.inf, 0.0, 0.0)
            for i in range(len(rx) - 1):
                for px, py in ((rx[i], ry[i]), ((rx[i] + rx[i + 1]) / 2, (ry[i] + ry[i + 1]) / 2)):
                    _, _, _, d = closest_on_segments(px, py, ax, ay, bx, by)
                    if d < best[0]:
                        best = (d, px, py)
            ol, oo = _latlon(lat, lon, best[1], best[2])
            out.proposals.append(
                Proposal(
                    "outline_nearest_road",
                    ol,
                    oo,
                    float(np.hypot(best[1], best[2])),
                    f"{best[0]:.0f} m from the road",
                )  # fmt: skip
            )
        pax, pay, pbx, pby, _, ends = self._road_segments(lat, lon, PATH_KINDS)
        for ex, ey in ends:
            _, qx, qy, d = closest_on_segments(ex, ey, rx[:-1], ry[:-1], rx[1:], ry[1:])
            if d <= PATH_END_M:
                ql, qo = _latlon(lat, lon, qx, qy)
                out.proposals.append(
                    Proposal("path_endpoint", ql, qo, float(np.hypot(qx, qy)), f"{d:.0f} m gap", d)
                )
        # path endpoints: the one closest to the outline first (deterministic, no oracle choice)
        out.proposals.sort(key=lambda p: (p.kind == "path_endpoint", p.gap_m))
        return out
