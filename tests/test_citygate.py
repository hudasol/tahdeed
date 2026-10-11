"""City gate: no city evidence + a comparably scored rival in another city => ask, don't guess."""

from types import SimpleNamespace

import pytest

from tahdeed import calibrate
from tahdeed.calibrate import Policy, decide
from tahdeed.resolve import Candidate, Flags


def _g():
    row = lambda city: (0, "1", "", "", "", "", "", "", city)  # noqa: E731
    return SimpleNamespace(addr=[row("dubai"), row("sharjah"), row("dubai")], pois=[], areas=[])


def _cand(i, p50, p_valid, tier="address", rival=False):
    c = Candidate(tier, 25.0 + i * 0.1, 55.0, 10.0, ref=("addr", i), p50=p50, p_valid=p_valid)
    if rival:
        c.evidence = {"rival_only": True}
    return c


def _run(monkeypatch, cands, flags, cities=()):
    monkeypatch.setattr(calibrate, "_asks", lambda *a, **k: [])
    rs = SimpleNamespace(
        g=_g(), flags=flags, ranker=SimpleNamespace(policy=Policy(tau=0.5, ambiguity_margin=0.8))
    )
    ctx = {"cities": list(cities), "street_spans": []}
    return decide(rs, "q", None, [], cands, ctx, []), ctx


def test_gate_asks_when_rival_city_scores_comparably(monkeypatch):
    top = _cand(0, 0.9, 0.9)
    rival = _cand(1, 0.0, 0.5, tier="street", rival=True)
    res, ctx = _run(monkeypatch, [top, rival], Flags(city_gate=True, city_margin=0.35))
    assert res.status == "ambiguous" and res.best is top
    assert ctx["city_gate"][0] is top and rival in res.alternatives


def test_gate_silent_when_city_given_or_rival_weak_or_off(monkeypatch):
    top, rival = _cand(0, 0.9, 0.9), _cand(1, 0.0, 0.5, tier="street", rival=True)
    on = Flags(city_gate=True, city_margin=0.35)
    assert _run(monkeypatch, [top, rival], on, cities=["dubai"])[0].status == "resolved"
    weak = _cand(1, 0.0, 0.1, tier="street", rival=True)
    assert _run(monkeypatch, [top, weak], on)[0].status == "resolved"
    assert _run(monkeypatch, [top, rival], Flags(city_gate=False))[0].status == "resolved"


def test_same_city_rival_does_not_trigger(monkeypatch):
    top, same = _cand(0, 0.9, 0.9), _cand(2, 0.0, 0.8, tier="street", rival=True)
    res, _ = _run(monkeypatch, [top, same], Flags(city_gate=True, city_margin=0.35))
    assert res.status == "resolved"


def test_rival_only_candidates_are_never_the_answer(monkeypatch):
    rival = _cand(1, 0.99, 0.99, rival=True)
    res, _ = _run(monkeypatch, [rival], Flags(city_gate=True, city_margin=0.35))
    assert res.best is None or res.best is not rival


def test_default_margin_and_env_override(monkeypatch):
    assert Flags().city_margin == pytest.approx(0.35)
    monkeypatch.setenv("TAHDEED_CITY_MARGIN", "0.2")
    assert Flags().city_margin == pytest.approx(0.2)
