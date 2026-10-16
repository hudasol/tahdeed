"""EXPLORATORY last meter module on a tiny hand-made (synthetic) layout: one square building of
about 20 m with an entrance vertex on its south side, a road 10 m south of it and a footway."""

import json
import sqlite3

import pytest

from tahdeed.lastmeter import LastMeter, _xy, closest_on_segments, point_in_ring

LAT, LON = 24.45, 54.38
D = 0.0001  # about 11 m in latitude


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "lm.sqlite"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE buildings(id INTEGER PRIMARY KEY, lat REAL, lon REAL, ring TEXT);"
        "CREATE TABLE entrances(id INTEGER PRIMARY KEY, lat REAL, lon REAL, kind TEXT, building_id INTEGER);"
        "CREATE TABLE roads(id INTEGER PRIMARY KEY, kind TEXT, coords TEXT);"
    )
    ring = [
        [LAT - D, LON - D],
        [LAT - D, LON + D],
        [LAT + D, LON + D],
        [LAT + D, LON - D],
        [LAT - D, LON - D],
    ]
    con.execute("INSERT INTO buildings VALUES (1, ?, ?, ?)", (LAT, LON, json.dumps(ring)))
    con.execute("INSERT INTO entrances VALUES (10, ?, ?, 'main', 1)", (LAT - D, LON))
    road = [[LAT - 2 * D, LON - 5 * D], [LAT - 2 * D, LON + 5 * D]]
    con.execute("INSERT INTO roads VALUES (100, 'residential', ?)", (json.dumps(road),))
    path = [[LAT + 3 * D, LON + 3 * D], [LAT + 1.2 * D, LON + 0.5 * D]]
    con.execute("INSERT INTO roads VALUES (101, 'footway', ?)", (json.dumps(path),))
    con.commit()
    con.close()
    return p


def test_geometry_helpers():
    assert point_in_ring(0, 0, [-1, 1, 1, -1, -1], [-1, -1, 1, 1, -1])
    assert not point_in_ring(2, 0, [-1, 1, 1, -1, -1], [-1, -1, 1, 1, -1])
    i, cx, cy, d = closest_on_segments(0, 1, [-1], [0], [1], [0])
    assert (i, cx, cy, d) == (0, 0.0, 0.0, 1.0)


def test_proposals(db):
    lm = LastMeter(db)
    res = lm.propose(LAT, LON)
    assert res.exploratory and res.building_id == 1
    kinds = [p.kind for p in res.proposals]
    assert kinds[0] == "osm_entrance"
    assert {"centroid", "nearest_road_point", "outline_nearest_road", "path_endpoint"} <= set(kinds)
    out = next(p for p in res.proposals if p.kind == "outline_nearest_road")
    x, y = _xy(LAT, LON, out.lat, out.lon)
    assert y < 0  # on the south side, facing the road
    road = next(p for p in res.proposals if p.kind == "nearest_road_point")
    assert road.dist_from_input_m == pytest.approx(2 * D * 111_320, rel=0.01)


def test_entrances_can_be_hidden_and_far_points_have_no_building(db):
    lm = LastMeter(db)
    assert all(
        p.kind != "osm_entrance" for p in lm.propose(LAT, LON, use_entrances=False).proposals
    )
    assert lm.propose(LAT + 0.01, LON).building_id is None
