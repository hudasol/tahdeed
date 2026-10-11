"""Tests for the human-benchmark collection kit (bench/human_kit) and tahdeed.human.

Everything below that looks like volunteer data is a SYNTHETIC TEST FIXTURE built in memory or in
pytest's tmp_path to exercise the code. It is not benchmark data and must never be copied under
bench/ or used as a result.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tahdeed import human

KIT = Path(__file__).resolve().parents[1] / "bench" / "human_kit"


def _load_assign():
    spec = importlib.util.spec_from_file_location("human_kit_assign", KIT / "assign.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


assign_mod = _load_assign()

# ----------------------------------------------------------------------------- synthetic fixtures

SYNTHETIC_PLACES = [  # SYNTHETIC TEST FIXTURE: invented ids and coordinates
    ("P001", "Fixture Mall", "مول وهمي", "mall", "Dubai", "25.000000", "55.000000", "A"),
    (
        "P002",
        "Fixture Hospital",
        "مستشفى وهمي",
        "hospital",
        "Abu Dhabi",
        "24.500000",
        "54.400000",
        "B",
    ),
    ("P003", "Fixture Station", "محطة وهمية", "metro", "Dubai", "25.100000", "55.100000", "A"),
]


@pytest.fixture
def places_csv(tmp_path):
    p = tmp_path / "places.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "place_id",
                "name_en",
                "name_ar",
                "category",
                "emirate",
                "lat",
                "lon",
                "verified_level",
            ]
        )
        w.writerows(SYNTHETIC_PLACES)
    return p


def make_doc(code="TEST-AAA1", responses=None, consent=True):
    """SYNTHETIC TEST FIXTURE response document."""
    return {
        "schema_version": "1",
        "kit": "tahdeed-human-kit",
        "created": "2000-01-01",
        "volunteer_code": code,
        "consent": {"agreed": consent, "version": "1"},
        "demographics": {"emirate_residence": "dubai", "years_in_uae": "1-5"},
        "responses": responses
        if responses is not None
        else [{"place_id": "P001", "text": "synthetic fixture text one"}],
    }


def write_docs(tmp_path, docs):
    paths = []
    for i, d in enumerate(docs):
        p = tmp_path / f"r{i}.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        paths.append(p)
    return paths


def run_ingest(tmp_path, docs, places_csv, salt="s1"):
    out = tmp_path / "out.jsonl"
    salt_file = tmp_path / "salt.txt"
    salt_file.write_text(salt, encoding="utf-8")
    logs: list[str] = []
    stats = human.ingest(
        write_docs(tmp_path, docs), out, places_csv=places_csv, salt_file=salt_file, log=logs.append
    )
    recs = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    return stats, recs


# ----------------------------------------------------------------------------- validation


def test_schema_accepts_good_and_rejects_bad():
    schema = human.load_schema()
    assert human.validate(make_doc(), schema) == []
    bad = make_doc(consent=False)
    assert any(p == "/consent/agreed" for p, _ in human.validate(bad, schema))
    extra = make_doc()
    extra["name"] = "not allowed"
    assert any("unexpected" in m for _, m in human.validate(extra, schema))
    badplace = make_doc(responses=[{"place_id": "X1", "text": "synthetic"}])
    assert any(p.startswith("/responses/0") for p, _ in human.validate(badplace, schema))


def test_file_without_consent_is_rejected_whole(tmp_path, places_csv):
    stats, recs = run_ingest(tmp_path, [make_doc(consent=False)], places_csv)
    assert recs == []
    assert stats["files_rejected"] == 1


def test_invalid_entry_dropped_but_file_kept(tmp_path, places_csv):
    doc = make_doc(
        responses=[
            {"place_id": "BAD", "text": "synthetic fixture"},
            {"place_id": "P002", "text": "synthetic fixture two"},
        ]
    )
    stats, recs = run_ingest(tmp_path, [doc], places_csv)
    assert [r["place_id"] for r in recs] == ["P002"]
    assert stats["dropped_invalid_entry"] == 1


# ----------------------------------------------------------------------------- cleaning


def test_pii_redaction_and_makani_kept():
    t, flags = human.clean_text(
        "call 050 123 4567 or a.b@example.com, insta @some_handle, see https://x.example.com/a "
        "ref 123456789012 and makani 12345 67890"
    )
    for leaked in ("050", "example.com", "@some_handle", "https", "123456789012"):
        assert leaked not in t
    assert "12345 67890" in t  # 10-digit Makani is address information, kept
    for k in ("phone", "email", "handle", "url", "long_digits"):
        assert f"pii_redacted:{k}" in flags


def test_arabic_indic_digits_phone_redacted():
    t, flags = human.clean_text("اتصل ٠٥٠١٢٣٤٥٦٧ جنب المسجد")
    assert "٠٥٠" not in t and "050" not in t
    assert any(f.startswith("pii_redacted") for f in flags)
    assert "جنب المسجد" in t


@pytest.mark.parametrize(
    "text",
    [
        "my villa 12 near the gate",
        "next to my house",
        "flat 304 second floor",
        "فيلا رقم 5 جنب المسجد",
        "بيتي قريب",
    ],
)
def test_personal_address_flagged_not_removed(text):
    t, flags = human.clean_text(text)
    assert "review:possible_personal_address" in flags
    assert len(t) >= len(text.translate(human._AR_DIGITS).strip()) - 2


def test_landmark_text_not_flagged():
    _, flags = human.clean_text("near the main gate, opposite the petrol station, Al Wahda")
    assert flags == []


@pytest.mark.parametrize(
    "text,want",
    [
        ("near the main gate, opposite the petrol station", "en"),
        ("جنب البوابة الرئيسية مقابل المحطة", "ar"),
        ("3ala yameen ba3d el bawwaba", "arabizi"),
        ("sha3bi 7ay near the mosque", "arabizi"),
        ("جنب البوابة opposite the petrol station", "mixed"),
        ("2nd floor, 5th street", "en"),
    ],
)
def test_detect_script(text, want):
    assert human.detect_script(text) == want


# ----------------------------------------------------------------------------- ingest behaviour


def test_dedupe_incomplete_skipped_unknown(tmp_path, places_csv):
    doc1 = make_doc(
        responses=[
            {"place_id": "P001", "text": "synthetic first answer"},
            {"place_id": "P001", "text": "synthetic duplicate answer"},  # duplicate pair
            {"place_id": "P002", "text": "  "},  # incomplete
            {"place_id": "P003", "text": "ab"},  # too short
            {"place_id": "P003", "skipped": True},  # skipped
            {"place_id": "P099", "text": "synthetic unknown place"},  # not in places.csv
        ]
    )
    doc2 = make_doc(
        code="TEST-BBB2", responses=[{"place_id": "P001", "text": "synthetic other volunteer"}]
    )
    stats, recs = run_ingest(tmp_path, [doc1, doc2], places_csv)
    assert len(recs) == 2
    assert stats["dropped_duplicate"] == 1
    assert stats["dropped_incomplete"] == 2
    assert stats["dropped_skipped"] == 1
    assert stats["dropped_unknown_place"] == 1
    assert stats["volunteers"] == 2
    first = [r for r in recs if r["text"] == "synthetic first answer"]
    assert len(first) == 1  # first wins


def test_same_file_twice_is_deduped(tmp_path, places_csv):
    d = make_doc()
    _, recs = run_ingest(tmp_path, [d, d], places_csv)
    assert len(recs) == 1


def test_codes_replaced_by_salted_hash(tmp_path, places_csv):
    doc = make_doc(code="SECRETCODE-9")
    _, a = run_ingest(tmp_path, [doc], places_csv, salt="saltA")
    (tmp_path / "out.jsonl").unlink()
    _, b = run_ingest(tmp_path, [doc], places_csv, salt="saltB")
    raw = json.dumps(a)
    assert "SECRETCODE" not in raw
    assert a[0]["volunteer_bucket"] != b[0]["volunteer_bucket"]
    assert set(a[0]) >= {"query_id", "place_id", "text", "script", "volunteer_bucket", "flags"}


def test_review_flag_on_reused_text(tmp_path, places_csv):
    doc = make_doc(
        responses=[
            {"place_id": "P001", "text": "synthetic same text"},
            {"place_id": "P002", "text": "Synthetic Same Text"},
        ]
    )
    _, recs = run_ingest(tmp_path, [doc], places_csv)
    assert all("review:same_text_for_several_places" in r["flags"] for r in recs)


def test_csv_transcription_supported(tmp_path, places_csv):
    p = tmp_path / "t.csv"
    p.write_text(
        "volunteer_code,consent_agreed,consent_version,emirate_residence,years_in_uae,place_id,text,script_self\n"
        "TEST-CSV1,yes,1,dubai,gt10,P001,synthetic csv text,en\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.jsonl"
    stats = human.ingest([p], out, places_csv=places_csv, log=lambda *_: None)
    assert stats["records_written"] == 1


# ----------------------------------------------------------------------------- evaluate


class FakeResolver:
    """SYNTHETIC TEST FIXTURE resolver: returns the truth point of 'Fixture Mall' when asked."""

    def __init__(self):
        self.calls = []

    def resolve(self, text):
        self.calls.append(text)
        if "Fixture Mall" in text and "far" not in text:
            return SimpleNamespace(status="resolved", best=SimpleNamespace(lat=25.0, lon=55.0))
        if "far" in text:
            return SimpleNamespace(status="approximate", best=SimpleNamespace(lat=25.5, lon=55.5))
        return SimpleNamespace(status="unresolved", best=None)


def _write_jsonl(path, n, text="synthetic fixture text"):
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n):
            rec = {
                "query_id": f"q{i}",
                "place_id": "P001",
                "text": text if i % 2 == 0 else "far synthetic fixture",
                "script": "en",
                "volunteer_bucket": f"v{i % 5}",
                "flags": [],
            }
            fh.write(json.dumps(rec) + "\n")


def test_evaluate_pending_when_missing(tmp_path, places_csv):
    out: list[str] = []
    assert human.evaluate(tmp_path / "nope.jsonl", places_csv, write=out.append) is None
    assert out == ["pending real data"]


def test_evaluate_pending_when_fewer_than_20(tmp_path, places_csv):
    p = tmp_path / "h.jsonl"
    _write_jsonl(p, 19)
    out: list[str] = []
    r = FakeResolver()
    assert human.evaluate(p, places_csv, resolver=r, write=out.append) is None
    assert out[0] == "pending real data"
    assert r.calls == []  # no numbers, no resolver run
    assert not any("%" in line for line in out)


def test_evaluate_numbers(tmp_path, places_csv):
    p = tmp_path / "h.jsonl"
    _write_jsonl(p, 20)
    out: list[str] = []
    s = human.evaluate(
        p, places_csv, resolver=FakeResolver(), write=out.append, out_json=tmp_path / "r.json"
    )
    o = s["overall"]
    assert o["n"] == 20 and o["volunteers"] == 5
    assert o["status"] == {"resolved": 10, "approximate": 10}
    assert o["text_within_50m"]["k"] == 10
    assert o["text_within_1000m"]["k"] == 10
    assert (o["resolved_precision_50m"]["k"], o["resolved_precision_50m"]["n"]) == (10, 10)
    assert "en" in s["by_script"]
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["overall"]["n"] == 20
    assert any("N=20" in line for line in out)


def test_evaluate_excludes_review_flagged(tmp_path, places_csv):
    p = tmp_path / "h.jsonl"
    _write_jsonl(p, 24)
    lines = p.read_text(encoding="utf-8").splitlines()
    recs = [json.loads(x) for x in lines]
    for r in recs[:5]:
        r["flags"] = ["review:possible_personal_address"]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    out: list[str] = []
    assert human.evaluate(p, places_csv, resolver=FakeResolver(), write=out.append) is None
    assert out[0] == "pending real data"  # only 19 usable once flagged records are held back
    s2 = human.evaluate(
        p, places_csv, resolver=FakeResolver(), include_flagged=True, write=lambda *_: None
    )
    assert s2["overall"]["n"] == 24


def test_wilson_interval():
    p, lo, hi = human.wilson(50, 100)
    assert p == 0.5 and 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    assert human.wilson(0, 0)[0] != human.wilson(0, 0)[0]  # nan
    _, lo0, hi0 = human.wilson(0, 10)
    assert lo0 == 0.0 and hi0 > 0.2


def test_cli_evaluate_pending(tmp_path, capsys):
    assert human.main(["evaluate", str(tmp_path / "missing.jsonl")]) == 0
    assert capsys.readouterr().out.strip() == "pending real data"


# ----------------------------------------------------------------------------- assignment


def _real_places():
    return assign_mod.load_places(KIT / "places.csv")


def test_assignment_balanced_and_deterministic():
    places = _real_places()
    codes = [f"CODE{i:02d}" for i in range(35)]
    a = assign_mod.assign(codes, places)
    assert a == assign_mod.assign(codes, places)
    assert assign_mod.assign(codes, places, seed="other") != a
    rep = assign_mod.coverage_report(a, places)
    assert rep["uncovered"] == []
    assert rep["min_cover"] >= 1 and rep["max_cover"] - rep["min_cover"] <= 3
    for sheet in a.values():
        assert len(sheet) == 5 and len({p["place_id"] for p in sheet}) == 5
        assert len({p["category"] for p in sheet}) >= 4
        assert len({p["emirate"] for p in sheet}) >= 3
    cats = rep["by_category"]
    assert min(cats[c] for c in ("mall", "hospital", "university")) >= 25


def test_assignment_respects_min_level_and_never_leaks_coordinates():
    only_a = assign_mod.load_places(KIT / "places.csv", min_level="A")
    assert only_a and all(p["verified_level"] == "A" for p in only_a)
    sheet = assign_mod.sheet_json("CODE01", _real_places()[:5])
    raw = json.dumps(sheet)
    assert "lat" not in raw and "lon" not in raw and "source" not in raw
    assert set(sheet["places"][0]) == {"place_id", "name_en", "name_ar", "category"}


def test_assignment_rejects_duplicate_codes():
    with pytest.raises(ValueError):
        assign_mod.assign(["A", "A"], _real_places())


def test_embed_in_form_roundtrip():
    tpl = (KIT / "form" / "index.html").read_text(encoding="utf-8")
    sheet = assign_mod.sheet_json("CODE01", _real_places()[:5])
    html = assign_mod.embed_in_form(tpl, sheet)
    m = re.search(r'<script id="assignments" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(m.group(1)) == {"CODE01": sheet}


# ----------------------------------------------------------------------------- shipped files


def test_places_csv_integrity():
    rows = list(csv.DictReader(open(KIT / "places.csv", newline="", encoding="utf-8")))
    assert len(rows) >= 60
    assert len({r["place_id"] for r in rows}) == len(rows)
    assert {r["verified_level"] for r in rows} <= {"A", "B"}
    cats = [r["category"] for r in rows]
    assert cats.count("mall") >= 12 and cats.count("hospital") >= 10
    assert cats.count("metro") >= 10 and cats.count("university") >= 10
    assert cats.count("public_building") + cats.count("park") >= 10
    assert {r["emirate"] for r in rows} >= {
        "Abu Dhabi",
        "Dubai",
        "Sharjah",
        "Ajman",
        "Al Ain",
        "Ras Al Khaimah",
        "Fujairah",
    }
    for r in rows:
        assert 22.5 < float(r["lat"]) < 26.5 and 51.0 < float(r["lon"]) < 56.6
        assert r["source_urls"].startswith("https://www.openstreetmap.org/")
        assert r["name_en"] and r["coord_source_primary"]
        # no commercial geocoder may appear as a source
        assert not re.search(r"google|apple|mapbox|here\.com", r["coord_source_secondary"], re.I)
        if r["verified_level"] == "A":
            assert "Wikidata" in r["coord_source_secondary"] and "disagree" not in r["notes"]


def test_form_is_offline_and_cookie_free():
    html = (KIT / "form" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"""(?:src|href|action)\s*=\s*["']?\s*(?:https?:)?//""", html, re.I)
    for banned in (
        "fetch(",
        "XMLHttpRequest",
        "document.cookie",
        "localStorage",
        "sessionStorage",
        "sendBeacon",
        "WebSocket",
    ):
        assert banned not in html
    assert "default-src 'none'" in html
    assert 'dir="rtl"' in html or "dir=lang" in html or "documentElement.dir" in html
    assert '<script id="assignments" type="application/json">' in html


def test_schema_file_matches_form_output_shape():
    schema = json.loads((KIT / "form" / "schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["kit"]["const"] == "tahdeed-human-kit"
    html = (KIT / "form" / "index.html").read_text(encoding="utf-8")
    for key in (
        "schema_version",
        "volunteer_code",
        "consent",
        "demographics",
        "responses",
        "pii_warning_acknowledged",
    ):
        assert (
            key in html
            and key
            in schema["properties"] | schema["properties"]["responses"]["items"]["properties"]
        )


def test_template_csv_header_matches_ingest():
    header = (KIT / "form" / "responses_template.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == [
        "volunteer_code",
        "consent_agreed",
        "consent_version",
        "emirate_residence",
        "years_in_uae",
        "place_id",
        "text",
        "script_self",
    ]
