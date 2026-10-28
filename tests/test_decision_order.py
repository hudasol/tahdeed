"""A valid fine candidate is offered ahead of a coarse city when the fine answer is not resolved."""

from types import SimpleNamespace

from tahdeed import calibrate
from tahdeed.calibrate import Policy, decide
from tahdeed.resolve import Candidate, Resolver


def _run(monkeypatch, cands):
    monkeypatch.setattr(calibrate, "_asks", lambda *a, **k: [])
    rs = SimpleNamespace(
        g=None,
        flags=SimpleNamespace(city_gate=False),
        ranker=SimpleNamespace(policy=Policy(tau=0.5, ambiguity_margin=0.8)),
    )
    return decide(rs, "q", None, [], cands, {"cities": [], "street_spans": []}, [])


def _poi(p50, p_valid):
    return Candidate("poi", 25.12, 55.2, 25.0, ref=("poi", 0), p50=p50, p_valid=p_valid)


def _city(p_valid):
    return Candidate("city", 25.2, 55.27, 90000.0, ref=("city", 0), p50=0.0, p_valid=p_valid)


def test_valid_poi_beats_city(monkeypatch):
    poi, city = _poi(0.29, 0.56), _city(0.96)
    res = _run(monkeypatch, [city, poi])
    assert res.status == "approximate" and res.best is poi


def test_weak_poi_does_not_beat_city(monkeypatch):
    poi, city = _poi(0.05, 0.30), _city(0.96)
    res = _run(monkeypatch, [city, poi])
    assert res.best is city


def test_approximate_poi_radius_is_not_a_door():
    rs = SimpleNamespace(ranker=SimpleNamespace(radii={"area": 5000.0}))
    c = _poi(0.29, 0.56)
    c.p200, c.p1k = 0.5, 0.95
    Resolver._apply_radius(rs, c, "approximate")
    assert c.radius_m == 1000.0
    c.p50 = 0.95
    c.radius_m = 25.0
    Resolver._apply_radius(rs, c, "resolved")
    assert c.radius_m == 25.0


def test_skeleton_only_poi_is_not_a_name_match():
    from tahdeed.resolve import _poi_named

    adib = (1, "ADIB", None, "ADIB", "bank", None, "dubai", None, 25.0, 55.0, "n1")
    dubai = (2, "Dubai", None, None, "x", None, "dubai", None, 25.0, 55.0, "n2")
    assert not _poi_named(adib, "dubai")
    assert _poi_named(dubai, "dubai")


def test_same_name_features_count_as_one_place():
    from tahdeed.resolve import _n_places

    def row(lat, lon):
        return (0, "n", None, "n", "mall", None, "dubai", None, lat, lon, "x")

    g = SimpleNamespace(
        pois=[row(25.1200, 55.2000), row(25.1210, 55.2005), row(25.2000, 55.3000), row(24.4, 54.4)]
    )
    assert _n_places(g, [0, 1]) == 1
    assert _n_places(g, [0, 1, 2, 3]) == 3
    assert _n_places(g, [2]) == 1
