"""Cross-city test set and metrics: names that exist in several cities.

The failure this targets: a street or POI name that exists in more than one city, written without
the city, answered confidently in the wrong one. The queries are SYNTHETIC (rendered from OSM
records with light noise), paired across evidence levels so that the only thing that changes is
how much city evidence the text contains:

* ``E0`` house number + street name only (no area, no city)
* ``E1`` + the district name
* ``E2`` + the city name (control: the gate must not change these)

Strata: ``named`` streets, ``numbered`` streets ("Street 5"), ``poi`` names (chains, malls).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import numpy as np

from .gazetteer import Gazetteer, keys_of
from .geo import haversine_m
from .noise import Query, abbreviate, perturb_translit, split_of, typo

EVIDENCE = ("E0", "E1", "E2")
_NUMBERED = re.compile(r"^(street|road|lane|شارع|ممر|طريق)?\s*\d+$", re.I)
GOLD_CASES = Path(__file__).resolve().parents[2] / "tests" / "gold" / "gold_v1.json"


def _multi_city_keys(g: Gazetteer) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for k, ids in g.addr_by_street.items():
        cs: dict[str, int] = {}
        for i in ids:
            cs[g.addr[i][8]] = cs.get(g.addr[i][8], 0) + 1
        if len(cs) >= 2:
            out[k] = cs
    return out


def _noisy(text: str, rng: random.Random, tags: list[str]) -> str:
    if rng.random() < 0.3:
        text, ch = abbreviate(text)
        if ch:
            tags.append("abbr")
    if rng.random() < 0.3:
        text, ch = perturb_translit(text, rng, consonant=False)
        if ch:
            tags.append("vowel")
    if rng.random() < 0.2:
        text, ch = typo(text, rng)
        if ch:
            tags.append("typo")
    return text


def make_crosscity_queries(
    g: Gazetteer, split: str, n_named: int = 600, n_numbered: int = 300, n_poi: int = 300,
    seed: int = 0,
) -> list[Query]:  # fmt: skip
    """Paired queries: every truth is rendered at each evidence level."""
    rng = random.Random(f"{seed}-cc-{split}")
    multi = _multi_city_keys(g)
    named: list[tuple[int, str]] = []
    numbered: list[tuple[int, str]] = []
    for i, a in enumerate(g.addr):
        if not (a[1] and (a[2] or a[3])) or split_of(f"{a[8]}|{a[5] or a[4] or ''}") != split:
            continue
        k = next((k for k in sorted(g.addr_street_keys[i]) if k in multi), None)
        if k is None:
            continue
        (numbered if _NUMBERED.match((a[3] or a[2] or "").strip()) else named).append((i, k))
    rng.shuffle(named)
    rng.shuffle(numbered)

    out: list[Query] = []
    for stratum, pool, n in (("named", named, n_named), ("numbered", numbered, n_numbered)):
        for i, k in pool[:n]:
            a = g.addr[i]
            cs = multi[k]
            lang = "ar" if (a[2] and (not a[3] or rng.random() < 0.35)) else "en"
            street = (a[2] if lang == "ar" else a[3]) or a[2] or a[3]
            area = (a[4] if lang == "ar" else a[5]) or a[5] or a[4]
            city = g.city_name(a[8])[1 if lang == "ar" else 0]
            tags: list[str] = []
            street = _noisy(street, rng, tags) if lang == "en" else street
            parts = {"E0": [a[1], street], "E1": [a[1], street, area], "E2": [a[1], street, city]}
            for ev in EVIDENCE:
                if ev == "E1" and not area:
                    continue
                text = ", ".join(str(p) for p in parts[ev][:2]) if ev == "E0" else None
                if text is None:
                    text = f"{parts[ev][0]} {parts[ev][1]}, {parts[ev][2]}"
                else:
                    text = f"{parts[ev][0]} {parts[ev][1]}"
                out.append(
                    Query(text, "addr", i, a[12], a[13], tags + [f"cc_{stratum}", ev],
                          "cc", split, lang,
                          extra={"stratum": stratum, "evidence": ev, "truth_city": a[8],
                                 "n_cities": len(cs), "pair": f"a{i}",
                                 "truth_majority": cs[a[8]] == max(cs.values())})
                )  # fmt: skip

    # POI names present in several cities
    pk: dict[str, set[str]] = {}
    pidx: dict[int, str] = {}
    for i, p in enumerate(g.pois):
        for kk in keys_of(p[3], p[2]):
            if len(kk) >= 4:
                pk.setdefault(kk, set()).add(p[6])
    pool_p: list[int] = []
    for i, p in enumerate(g.pois):
        if not (p[3] or p[2]) or split_of(f"poi|{p[6]}|{p[5]}") != split:
            continue
        ks = [kk for kk in keys_of(p[3], p[2]) if len(kk) >= 4 and len(pk.get(kk, ())) >= 2]
        if ks:
            pool_p.append(i)
            pidx[i] = ks[0]
    rng.shuffle(pool_p)
    for i in pool_p[:n_poi]:
        p = g.pois[i]
        lang = "ar" if (p[2] and (not p[3] or rng.random() < 0.3)) else "en"
        name = (p[2] if lang == "ar" else p[3]) or p[3] or p[2]
        city = g.city_name(p[6])[1 if lang == "ar" else 0]
        cs_n = len(pk[pidx[i]])
        for ev, text in (("E0", name), ("E2", f"{name}, {city}")):
            out.append(
                Query(text, "poi", i, p[8], p[9], ["cc_poi", ev], "cc", split, lang,
                      extra={"stratum": "poi", "evidence": ev, "truth_city": p[6],
                             "n_cities": cs_n, "pair": f"p{i}", "truth_majority": None})
            )  # fmt: skip
    return out


def gold_regression_cases(g: Gazetteer) -> list[Query]:
    """The hand-written queries that produced confident wrong answers in v2.0 (kept as cases)."""
    want = {
        "6 شارع الديرة الطوية",
        "4 Arqoub Qata st Dhahir Al Ain",
        "9 Haboub st Tiwayya",
        "138 Al Dhahar st Rawdat Al Reef",
    }
    rows = json.loads(GOLD_CASES.read_text(encoding="utf-8"))
    by_ll = {(round(a[12], 7), round(a[13], 7)): i for i, a in enumerate(g.addr)}
    out = []
    for r in rows:
        if r["query"] not in want:
            continue
        i = by_ll.get((round(r["lat"], 7), round(r["lon"], 7)))
        if i is None:
            continue
        out.append(
            Query(r["query"], "addr", i, r["lat"], r["lon"], ["cc_gold"], "cc", "gold", "mixed",
                  extra={"stratum": "gold", "evidence": "E1", "truth_city": g.addr[i][8],
                         "n_cities": 0, "pair": f"g{i}", "truth_majority": None})
        )  # fmt: skip
    return out


# ----------------------------------------------------------------------------- metrics


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(c - h), float(c + h))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n if n else None), "ci95": [lo, hi]}


def summarize_cc(ev: list[dict]) -> dict:
    """Per (stratum, evidence) cell: coverage, confident-wrong-city rate, abstain-for-city rate.

    * ``confident_wrong_city`` = P(answer city != truth city | status == resolved)
    * ``wrong_city_of_all``    = P(resolved and wrong city) over all queries (what a user meets)
    * ``coverage``             = P(status == resolved)
    * ``asked_city``           = P(status == ambiguous because of a cross-city rival)
    """
    cells: dict[str, dict] = {}
    keys = sorted({(e["stratum"], e["evidence"]) for e in ev})
    for s, evd in keys + [("all", e) for e in sorted({e for _, e in keys})]:
        sel = [e for e in ev if (s == "all" or e["stratum"] == s) and e["evidence"] == evd]
        n = len(sel)
        res = [e for e in sel if e["status"] == "resolved"]
        wrong = [e for e in res if e["wrong_city"]]
        cells[f"{s}/{evd}"] = {
            "n": n,
            "coverage": rate(len(res), n),
            "confident_wrong_city": rate(len(wrong), len(res)),
            "wrong_city_of_all": rate(len(wrong), n),
            "asked_city": rate(sum(1 for e in sel if e.get("city_gate")), n),
            "resolved_within_50m": rate(sum(1 for e in res if e["within50"]), len(res)),
        }
    return cells


def haversine_to(q: Query, lat: float, lon: float) -> float:
    return haversine_m(q.lat, q.lon, lat, lon)
