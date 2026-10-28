"""Parsing and filtering for the OSM independent sets. Inline fixtures only: no network."""

import json
from pathlib import Path

from tahdeed import bench
from tahdeed import bench_external as be


def _rec(i="id1", name="Blue Cafe", addr="Ground Floor, Dubai Mall, Financial Centre Road", **kw):
    r = {"id": i, "name": name, "address": addr, "category": "cafe", "confidence": 0.9,
         "operating_status": None, "lat": 25.1972, "lon": 55.2744,
         "sources": [{"dataset": "meta", "license": "CDLA-Permissive-2.0"}]}  # fmt: skip
    r.update(kw)
    return r


def test_good_record_becomes_a_row_with_licence_and_stratum():
    row = be.clean_overture_record(_rec())
    assert row["text"] == "Blue Cafe, Ground Floor, Dubai Mall, Financial Centre Road"
    assert row["stratum"] == "dubai" and row["truth_city"] == "dubai"
    assert row["source_licenses"] == ["CDLA-Permissive-2.0"] and row["synthetic"] is False
    assert row["truth_ref"] == "overture/id1" and row["hole"] is False


def test_name_already_in_address_is_not_repeated():
    row = be.clean_overture_record(_rec(addr="Blue Cafe, Dubai Mall, Financial Centre Road"))
    assert row["text"].startswith("Blue Cafe, Dubai Mall")
    assert row["text"].count("Blue Cafe") == 1


def test_records_that_must_not_be_published_are_dropped():
    bad = [
        _rec(category="home_service"),  # not a public venue
        _rec(confidence=0.3),
        _rec(operating_status="permanently_closed"),
        _rec(name="Dr. Aisha Khan"),  # title: possible individual
        _rec(name="Aisha Khan"),  # looks like a person
        _rec(addr="Villa 12, Street 4, Al Barsha"),  # residence
        _rec(addr="Call +971 50 123 4567, Dubai Mall, Dubai"),  # phone
        _rec(addr="Dubai Mall, info@example.com, Dubai"),  # email
        _rec(addr="Dubai Mall, see https://example.org/x"),  # link
        _rec(lat=25.29, lon=51.53),  # Doha, outside the UAE
        _rec(sources=[]),  # no recorded licence
        _rec(addr="Dubai"),  # too short to be an address
    ]
    for r in bad:
        assert be.clean_overture_record(r) is None, r


def test_venue_and_privacy_helpers():
    assert be.is_public_venue("hospital") and be.is_public_venue("thai_restaurant")
    assert not be.is_public_venue("real_estate_agent") and not be.is_public_venue(None)
    assert (
        be.looks_private("Mohammed bin Rashid", "Street 1") is False
    )  # business word absent but not 2 caps
    assert be.looks_private("John Smith", "Street 1")
    assert not be.looks_private("Smith Medical Centre", "Street 1")
    assert be.looks_private("Blue Cafe", "Flat 3, Block C")


def test_sample_is_deterministic_stratified_and_caps_chains():
    recs = [_rec(i=f"d{i:03d}", name=f"Cafe {i}") for i in range(40)]
    recs += [
        _rec(i=f"c{i:03d}", name="Chain Cafe", addr=f"Branch {i}, Dubai Mall, Dubai")
        for i in range(10)
    ]
    recs += [_rec(i=f"a{i:03d}", name=f"Abu Cafe {i}", lat=24.47, lon=54.37) for i in range(10)]
    t = {"dubai": 12, "abu dhabi": 5, "sharjah": 3, "other": 2}
    a = be.sample_overture(recs, t, seed=1)
    b = be.sample_overture(list(reversed(recs)), t, seed=1)
    assert a == b  # independent of input order
    assert a != be.sample_overture(recs, t, seed=2)
    by = {s: sum(r["stratum"] == s for r in a) for s in t}
    assert by == {"dubai": 12, "abu dhabi": 5, "sharjah": 0, "other": 0}
    assert sum(r["text"].startswith("Chain Cafe") for r in a) <= be.NAME_CAP
    assert [r["id"] for r in a] == [f"overture_places-{i:05d}" for i in range(len(a))]
    assert all(not k.startswith("_") for r in a for k in r)


def _b(qid, label, lang, c="Point(55.27 25.20)", addr=None, street=None, hn=None):
    b = {"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
         "label": {"value": label, "xml:lang": lang}, "c": {"value": c}}  # fmt: skip
    if addr:
        b["addr"] = {"value": addr[0], "xml:lang": addr[1]}
    if street:
        b["streetLabel"] = {"value": street, "xml:lang": lang}
    if hn:
        b["hn"] = {"value": hn}
    return b


def test_parse_wikidata_rows():
    rows = be.parse_wikidata(
        [
            _b(
                "Q20",
                "Burj Khalifa",
                "en",
                addr=("1 Sheikh Mohammed bin Rashid Blvd, Downtown Dubai", "en"),
            ),
            _b(
                "Q20",
                "برج خليفة",
                "ar",
                addr=("1 Sheikh Mohammed bin Rashid Blvd, Downtown Dubai", "en"),
            ),
            _b("Q10", "Example Museum", "en", street="Al Wasl Road", hn="12"),
            _b(
                "Q30",
                "Far Away",
                "en",
                c="Point(51.5 25.3)",
                addr=("Somewhere in Doha Street", "en"),
            ),
            _b("Q40", "Has Phone", "en", addr=("Call +971 4 123 4567 Street", "en")),
            _b("Q50", "Q50", "en", addr=("Some long street address", "en")),
            _b("Q70", "Maison", "en", addr=("12 Rue de la Corniche, Dubai", "fr")),
            _b("Q60", "Two Places", "en", addr=("A long street address", "en")),
            _b(
                "Q60",
                "Two Places",
                "en",
                c="Point(55.40 25.30)",
                addr=("A long street address", "en"),
            ),
        ]
    )
    assert [r["truth_ref"] for r in rows] == ["wikidata/Q10", "wikidata/Q20", "wikidata/Q70"]
    q20 = rows[1]
    assert (
        q20["text"].startswith("Burj Khalifa, 1 Sheikh") and q20["stratum"] == "address_statement"
    )
    assert (q20["lat"], q20["lon"]) == (25.2, 55.27) and q20["source_licenses"] == ["CC0-1.0"]
    assert (
        rows[0]["stratum"] == "street_statement"
        and rows[0]["text"] == "Example Museum, 12 Al Wasl Road"
    )
    assert rows[0]["text_kind"] == "human_written" and rows[0]["synthetic"] is False


def test_written_rows_score_with_the_unchanged_scorer(tmp_path: Path):
    rows = be.sample_overture(
        [_rec(i=f"x{i}", name=f"Cafe {i}") for i in range(5)], {"dubai": 5}, seed=3
    )
    d = tmp_path / "ext"
    sha = be._write_set(d, "overture_places", rows)
    assert len(sha) == 64
    be._update_manifest(d, "overture_places", {"n": 5, "sha256": sha})
    be._update_manifest(d, "wikidata_addresses", {"n": 0})
    assert set(json.loads((d / "MANIFEST.json").read_text())["sets"]) == {
        "overture_places", "wikidata_addresses"}  # fmt: skip
    pred = tmp_path / "p.jsonl"
    pred.write_text(
        "\n".join(json.dumps({"id": r["id"], "lat": r["lat"], "lon": r["lon"]}) for r in rows)
    )
    o = bench.score(pred, d)["sets"]["overture_places"]["overall"]
    assert o["n"] == 5 and o["precision_50m"][0] == 1.0
