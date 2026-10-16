"""Clarification loop: answering "Which city?" with a `city` hint (resolver, API, batch, CLI)."""

import io
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tahdeed import calibrate
from tahdeed.api import create_app
from tahdeed.calibrate import Policy, decide
from tahdeed.resolve import Candidate, Flags, city_key
from tahdeed.standardize import resolution_json

ADDR = "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah"


@pytest.mark.parametrize(
    "hint,key",
    [("Al Ain", "al ain"), ("al ain", "al ain"), ("العين", "al ain"), ("AUH", "abu dhabi"),
     ("dubai", "dubai"), ("Ras Al Khaimah", "ras al khaimah"), ("Atlantis", None), ("", None)],
)  # fmt: skip
def test_city_key(hint, key):
    assert city_key(hint) == key


def test_gate_exposes_city_options(monkeypatch):
    monkeypatch.setattr(calibrate, "_asks", lambda *a, **k: [])
    row = lambda city: (0, "1", "", "", "", "", "", "", city)  # noqa: E731
    g = SimpleNamespace(addr=[row("dubai"), row("sharjah")], pois=[], areas=[])
    top = Candidate("address", 25.0, 55.0, 10.0, ref=("addr", 0), p50=0.9, p_valid=0.9)
    rival = Candidate("street", 25.3, 55.4, 10.0, ref=("addr", 1), p50=0.0, p_valid=0.6)
    rival.evidence = {"rival_only": True}
    rs = SimpleNamespace(
        g=g,
        flags=Flags(city_gate=True, city_margin=0.35),
        ranker=SimpleNamespace(policy=Policy(tau=0.5)),
    )
    res = decide(rs, "q", None, [], [top, rival], {"cities": [], "street_spans": []}, [])
    assert res.status == "ambiguous" and res.city_options == ["dubai", "sharjah"]


def test_resolver_applies_hint(resolver):
    res = resolver.resolve(ADDR, city="Abu Dhabi")
    assert res.city_hint == "abu dhabi"
    assert any("city hint applied: Abu Dhabi" in n for n in res.notes)
    assert res.query.endswith(", Abu Dhabi")
    j = resolution_json(res)
    assert j["city_hint"] == "abu dhabi" and j["best"] is not None
    assert "Abu Dhabi" in j["best"]["standard"]["en"]


def test_resolver_arabic_text_gets_arabic_city(resolver):
    res = resolver.resolve("شارع شبيب بن سعيد المهيري", city="abu dhabi")
    assert res.query.endswith("أبوظبي")


def test_resolver_hint_outside_answer_city_is_never_resolved(resolver, gaz):
    from tahdeed.resolve import candidate_city

    res = resolver.resolve(ADDR, city="Dubai")
    if res.status == "resolved":
        assert candidate_city(gaz, res.best) == "dubai"


def test_resolver_rejects_unknown_city(resolver):
    with pytest.raises(ValueError):
        resolver.resolve(ADDR, city="Atlantis")


def test_no_hint_is_unchanged(resolver):
    a = resolution_json(resolver.resolve(ADDR))
    b = resolution_json(resolver.resolve(ADDR, city=None))
    assert a == b and a["city_hint"] is None and a["city_options"] == []


def _client(resolver, monkeypatch, limit="0"):
    monkeypatch.delenv("TAHDEED_API_TOKEN", raising=False)
    monkeypatch.delenv("TAHDEED_LOG_RAW", raising=False)
    monkeypatch.setenv("TAHDEED_RATE_LIMIT", limit)
    return TestClient(create_app(resolver))


def test_api_city_hint(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)
    j = c.post("/resolve", json={"address": ADDR, "city": "Abu Dhabi"}).json()
    assert j["city_hint"] == "abu dhabi"
    assert c.post("/resolve", json={"address": ADDR, "city": "Atlantis"}).status_code == 422
    too_long = c.post("/resolve", json={"address": ADDR, "city": "x" * 41})
    assert too_long.status_code == 422


def test_api_city_hint_is_rate_limited(resolver, monkeypatch):
    c = _client(resolver, monkeypatch, limit="5")  # burst of 5
    codes = [
        c.post("/resolve", json={"address": ADDR, "city": "abu dhabi"}).status_code
        for _ in range(7)
    ]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


def test_api_city_hint_logs_key_not_text(resolver, monkeypatch, caplog):
    c = _client(resolver, monkeypatch)
    q = ADDR + " call 0509876543"
    with caplog.at_level(logging.DEBUG):
        r = c.post("/resolve", json={"address": q, "city": "Abu Dhabi"})
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert r.status_code == 200 and '"city_hint": "abu dhabi"' in logs
    assert "Shabib" not in logs and "0509876543" not in logs and "0509876543" not in r.text


def test_batch_city_column(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)
    data = f'address,city\n"{ADDR}",Abu Dhabi\n"{ADDR}",Atlantis\n"{ADDR}",\n'
    r = c.post("/resolve/batch", files={"file": ("a.csv", io.BytesIO(data.encode()))})
    lines = r.text.strip().splitlines()
    assert r.status_code == 200 and len(lines) == 4
    assert (
        "Unknown city value ignored." in lines[2]
        and "Atlantis" not in r.text.split("\n", 2)[2].split(",")[-2]
    )


def test_cli_city_flag(monkeypatch, resolver, capsys):
    from tahdeed import cli, service

    monkeypatch.setattr(service, "load_resolver", lambda *a, **k: resolver)
    assert cli.main(["resolve", ADDR, "--city", "Abu Dhabi", "--json"]) == 0
    assert '"city_hint": "abu dhabi"' in capsys.readouterr().out
    assert cli.main(["resolve", ADDR, "--city", "Atlantis"]) == 2
