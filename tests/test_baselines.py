"""Baselines on the mini fixture gazetteer. The public geocoders are stubbed: no network."""

import argparse
import json
from pathlib import Path

import pytest

from tahdeed import baselines as bl
from tahdeed.bench import read_predictions
from tahdeed.geo import haversine_m
from tahdeed.studies import TfidfBaseline, gazetteer_docs

FIXTURE = Path(__file__).parent / "fixtures" / "mini.sqlite"

QISAYS = (24.4861458, 54.3699078)  # "46 Al Qisays Street, Al Danah", fixture record n4715622480


def _row(i, text, hole=False, ref=None):
    return {"id": f"t-{i}", "set": "t", "text": text, "hole": hole, "truth_ref": ref}


def test_gazetteer_docs_cover_addresses_and_pois(gaz):
    docs, meta = gazetteer_docs(gaz, include_pois=True)
    assert len(docs) == len(meta) == len(gaz.addr) + len(gaz.pois)
    assert gazetteer_docs(gaz)[0] == docs[: len(gaz.addr)]  # the address only path is unchanged
    assert meta[0][3].startswith("addr/") and meta[-1][3].startswith("poi/")


def test_tfidf_and_bm25_find_the_record(gaz):
    rows = [_row(0, "46 Al Qisays Street Al Danah Abu Dhabi")]
    for system in ("tfidf", "bm25"):
        (p,) = bl.run_ranker(system, rows, str(FIXTURE))
        assert not p.get("abstain"), system
        assert haversine_m(p["lat"], p["lon"], *QISAYS) < 500, system
        assert p["city"] == "abu dhabi"


def test_poi_is_found_by_name_and_hole_record_is_excluded(gaz):
    rows = [
        _row(0, "Al Hilal Bank Hamdan Branch"),
        _row(1, "Al Hilal Bank Hamdan Branch", hole=True, ref="poi/n564947405"),
    ]
    docs, meta = gazetteer_docs(gaz, include_pois=True)
    for system in ("tfidf", "bm25"):
        a, b = bl.run_ranker(system, rows, str(FIXTURE))
        assert haversine_m(a["lat"], a["lon"], 24.4916234, 54.365301) < 1
        assert (b["lat"], b["lon"]) != (a["lat"], a["lon"])  # the truth record cannot be returned


def test_bm25_scores_rare_terms_higher_and_no_match_is_zero():
    m = bl.Bm25(["alpha beta", "alpha gamma", "alpha delta rareword"])
    s = m.scores("rareword alpha")
    assert s.argmax() == 2 and s[0] > 0
    assert m.scores("zzzz").max() == 0
    assert bl._best(m.scores("zzzz"), None) is None
    assert bl._best(m.scores("rareword"), 2) is None  # excluding the only match leaves nothing


def test_tfidf_class_keeps_the_study_interface(gaz):
    class Q:
        text = "Al Qisays Street 46"

    lat, lon = TfidfBaseline(gaz).predict(Q())
    assert isinstance(lat, float) and 24 < lat < 25


def test_lookup_parsed_exact_and_ambiguous_and_city(gaz):
    hit = bl.lookup_parsed(
        [("46", "house_number"), ("Thani Bin Murshid Al Rumaithi Street", "road")], gaz
    )
    assert hit and abs(hit[0] - 24.4869763) < 1e-6 and hit[2] == "abu dhabi"
    assert (
        bl.lookup_parsed(
            [
                ("46", "house_number"),
                ("Thani Bin Murshid Al Rumaithi Street", "road"),
                ("Dubai", "city"),
            ],
            gaz,
        )
        is None
    )  # wrong city: no answer
    poi = bl.lookup_parsed([("Emirates General Market", "house")], gaz)
    assert poi and abs(poi[0] - 24.4912825) < 1e-6
    assert bl.lookup_parsed([("nothing here", "road")], gaz) is None


def test_libpostal_is_never_simulated(monkeypatch):
    monkeypatch.setattr(bl, "have_libpostal", lambda: False)
    with pytest.raises(RuntimeError, match="not available"):
        bl.run_libpostal([_row(0, "x")], str(FIXTURE))


def test_public_geocoders_are_cached_and_throttled(tmp_path, monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        if "photon" in url:
            return {"features": [{"geometry": {"coordinates": [55.27, 25.2]}}]}
        return []

    monkeypatch.setattr(bl, "_fetch_json", fake)
    rows = [_row(0, "Dubai Mall"), _row(1, "Nowhere")]
    cache = tmp_path / "c.json"
    p = bl.run_public("photon", rows, cache, gap=0)
    assert p[0] == {"id": "t-0", "lat": 25.2, "lon": 55.27} and len(calls) == 2
    assert "bbox=" in calls[0] and "limit=1" in calls[0] and "q=Dubai+Mall" in calls[0]
    assert (
        bl.run_public("photon", rows, cache, gap=0) == p and len(calls) == 2
    )  # cache: no new requests
    n = bl.run_public("nominatim", rows[:1], None, gap=0)
    assert n == [{"id": "t-0", "abstain": True}] and "countrycodes=ae" in calls[-1]
    assert bl.USER_AGENT.startswith("tahdeed-bench/1.0 (+https://")


def test_gap_between_requests_is_enforced(monkeypatch):
    slept = []
    monkeypatch.setattr(bl.time, "sleep", slept.append)
    monkeypatch.setattr(bl, "_fetch_json", lambda url: [])
    bl.run_public("nominatim", [_row(0, "a"), _row(1, "b")], None, gap=5.0)
    assert slept and 0 < slept[0] <= 5.0


def test_stride_sample_skips_holes_and_is_even():
    rows = [{"id": f"s-{i}", "set": "s", "text": "x", "hole": i % 5 == 0} for i in range(100)]
    s = bl.stride_sample(rows, 10)
    assert len(s) == 10 and all(not r["hole"] for r in s)
    assert s == bl.stride_sample(rows, 10)


def test_cli_run_uses_ids_of_and_reports_blocked_libpostal(tmp_path, monkeypatch, capsys):
    d = tmp_path / "d"
    d.mkdir()
    rows = [
        {"id": f"s-{i}", "set": "s", "text": f"t{i}", "hole": False, "truth_ref": None}
        for i in range(6)
    ]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    ids = tmp_path / "ids.jsonl"
    ids.write_text(json.dumps({"id": "s-2"}) + "\n" + json.dumps({"id": "s-4"}) + "\n")
    monkeypatch.setattr(bl, "_fetch_json", lambda url: [{"lat": "25.0", "lon": "55.0"}])
    out = tmp_path / "o.jsonl"
    ns = argparse.Namespace(system="nominatim", set=None, data=str(d), db="", limit=3,
                            ids_of=str(ids), cache=str(tmp_path / "c.json"), out=str(out))  # fmt: skip
    monkeypatch.setattr(bl.time, "sleep", lambda s: None)
    assert bl.run(ns) == 0
    assert set(read_predictions(out)) == {"s-2", "s-4"}
    monkeypatch.setattr(bl, "have_libpostal", lambda: False)
    ns.system = "libpostal"
    assert bl.run(ns) == 3 and "not available" in capsys.readouterr().err
