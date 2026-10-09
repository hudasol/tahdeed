"""Ranking, calibrated confidence, abstention policy, and per-tier radii.

Two rankers share one interface (``score(candidates)`` sets ``p50`` and ``p_valid``):

* :class:`HeuristicRanker` - hand-set rules; the *uncalibrated baseline*.
* :class:`GBMRanker` - gradient-boosted trees on candidate features, each head followed by
  isotonic calibration fitted on districts the model never saw.

Definitions
-----------
``p50``      P(candidate is within 50 m of the true location). Fine tiers only.
``p_valid``  P(candidate is correct *at its own tier*): the right address / POI (within 50 m),
             the right street in the right city, the right area, the right city.
Coarse tiers do not claim a point; they carry an empirical 90% radius.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .gazetteer import keys_of
from .geo import haversine_m
from .resolve import FINE_TIERS, TIER_ORDER, Candidate, Resolution

FEATURES = [
    "tier", "street_quality", "street_fuzzy", "street_tokens", "street_key_len",
    "street_has_type", "city_consistent", "area_consistent", "n_street_addr", "n_groups",
    "n_body", "n_unexplained", "has_landmark", "has_hn", "n_same", "n_same_clusters",
    "hn_rank", "postcode_match", "gap", "span_m", "between", "spread_m", "n_cities",
    "group_size", "group_frac", "poi_quality", "poi_fuzzy", "poi_tokens", "poi_key_len",
    "n_poi_same", "poi_street_consistent", "area_given", "has_street", "poi_is_whole_query",
    "lm_quality", "lm_fuzzy", "lm_tokens", "lm_key_len", "lm_instances", "lm_is_area",
    "anchor_dist_m", "relation_radius", "has_anchor", "area_quality", "area_fuzzy",
    "area_tokens", "area_key_len", "area_instances", "area_n", "area_radius",
]  # fmt: skip

MIN_VALID = 0.15  # below this, even the best coarse candidate is not trusted


def featurize(c: Candidate) -> list[float]:
    f = c.features
    row = []
    for name in FEATURES:
        if name == "tier":
            row.append(float(TIER_ORDER.index(c.tier)))
        else:
            row.append(float(f.get(name, -1.0)))
    return row


# ----------------------------------------------------------------------------- ground truth


@dataclass
class Truth:
    lat: float
    lon: float
    street_keys: set[str]
    area_keys: set[str]
    city: str


def truth_of(g, q) -> Truth:
    if q.truth_kind == "addr":
        a = g.addr[q.truth_idx]
        return Truth(a[12], a[13], set(g.addr_street_keys[q.truth_idx]),
                     set(g.addr_area_keys[q.truth_idx]), a[8])  # fmt: skip
    p = g.pois[q.truth_idx]
    return Truth(p[8], p[9], set(keys_of(p[5])) if p[5] else set(), set(), p[6])


def tier_correct(c: Candidate, t: Truth, dist: float) -> bool:
    """Is this candidate right at its own tier? (label for the ``p_valid`` head)."""
    tier = c.tier
    if tier in ("address", "poi"):
        return dist <= 50.0
    if tier == "interpolated":
        return dist <= 250.0
    if tier == "landmark":
        return dist <= max(150.0, 2.0 * float(c.features.get("relation_radius", 100.0)))
    if tier in ("street", "street_area"):
        same_city = c.label.get("city_key") == t.city
        return bool(set(c.evidence.get("keys", [])) & t.street_keys) and same_city
    if tier == "area":
        if t.area_keys:
            return bool(set(c.evidence.get("area_keys", [])) & t.area_keys)
        return dist <= c.radius_m
    if tier == "city":
        return c.label.get("city_key") == t.city
    return False


# ----------------------------------------------------------------------------- rankers


class HeuristicRanker:
    """Hand-written confidence rules (the uncalibrated baseline)."""

    name = "heuristic"

    def __init__(self) -> None:
        self.policy = Policy(tau=0.85)

    def score(self, cands: list[Candidate]) -> None:
        for c in cands:
            c.p50 = self._p50(c) if c.tier in FINE_TIERS else 0.0
            c.p_valid = c.p50 if c.tier in FINE_TIERS else self._valid(c)

    @staticmethod
    def _p50(c: Candidate) -> float:
        f = c.features
        if c.tier == "address":
            p = 0.9 * f.get("street_quality", 1.0)
            if f.get("n_same", 1) > 1:
                p *= 0.6
            if f.get("area_consistent", 0) == -1 or f.get("city_consistent", 0) == -1:
                p *= 0.7
            return float(min(0.99, p))
        if c.tier == "poi":
            p = 0.7 * f.get("poi_quality", 1.0)
            if f.get("n_poi_same", 1) > 1:
                p *= 0.6
            return float(p)
        if c.tier == "interpolated":
            return 0.25
        return 0.1

    @staticmethod
    def _valid(c: Candidate) -> float:
        base = {"street_area": 0.8, "street": 0.6, "area": 0.7, "city": 0.9}.get(c.tier, 0.5)
        q = c.features.get("street_quality", c.features.get("area_quality", 1.0))
        return float(base * q)


@dataclass
class Policy:
    """Operating point: resolve only when calibrated p50 reaches ``tau``."""

    tau: float = 0.85
    ambiguity_margin: float = 0.5  # runner-up must be < margin * best to call it unambiguous
    min_separation_m: float = 100.0


@dataclass
class GBMRanker:
    model50: object = None
    iso50: object = None
    model_valid: object = None
    iso_valid: object = None
    policy: Policy = field(default_factory=Policy)
    radii: dict[str, float] = field(default_factory=dict)
    name: str = "gbm+isotonic"

    def raw_scores(self, cands: list[Candidate]):
        X = np.array([featurize(c) for c in cands])
        return self.model50.predict_proba(X)[:, 1], self.model_valid.predict_proba(X)[:, 1]

    def score(self, cands: list[Candidate]) -> None:
        if not cands:
            return
        r50, rv = self.raw_scores(cands)
        p50 = self.iso50.predict(r50) if self.iso50 is not None else r50
        pv = self.iso_valid.predict(rv) if self.iso_valid is not None else rv
        for c, a, b in zip(cands, p50, pv, strict=True):
            c.p50 = float(a) if c.tier in FINE_TIERS else 0.0
            c.p_valid = float(b)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self, fh)

    @staticmethod
    def load(path: str | Path) -> GBMRanker:
        with open(path, "rb") as fh:
            return pickle.load(fh)  # noqa: S301 - local file written by `tahdeed train`


# ----------------------------------------------------------------------------- decision


def _dist(a: Candidate, b: Candidate) -> float:
    return haversine_m(a.lat, a.lon, b.lat, b.lon)


def decide(resolver, text, pq, spans, cands, ctx, notes) -> Resolution:
    policy: Policy = getattr(resolver.ranker, "policy", None) or Policy()
    fine = sorted((c for c in cands if c.tier in FINE_TIERS), key=lambda c: -(c.p50 or 0.0))
    coarse = [c for c in cands if c.tier not in FINE_TIERS]
    coarse.sort(key=lambda c: (TIER_ORDER.index(c.tier), -(c.p_valid or 0.0)))
    trusted = [c for c in coarse if (c.p_valid or 0.0) >= MIN_VALID]

    asks = _asks(resolver, pq, ctx, fine, trusted)
    best: Candidate | None = None
    alts: list[Candidate] = []
    status = "unresolved"

    if fine and (fine[0].p50 or 0.0) >= policy.tau:
        top = fine[0]
        rivals = [c for c in fine[1:] if _dist(top, c) > policy.min_separation_m]
        best, alts = top, rivals[:3]
        if rivals and (rivals[0].p50 or 0.0) >= policy.ambiguity_margin * (top.p50 or 0.0):
            status = "ambiguous"
        else:
            status = "resolved"
    elif trusted:
        # most specific trusted tier, best p_valid within it
        tier0 = trusted[0].tier
        same = sorted((c for c in trusted if c.tier == tier0), key=lambda c: -(c.p_valid or 0.0))
        best = same[0]
        status = "approximate"
        alts = [c for c in (fine[:2] + same[1:3] + trusted) if c is not best][:3]
    elif fine and (fine[0].p_valid or 0.0) >= MIN_VALID:
        best, status = fine[0], "approximate"
        alts = fine[1:3]
    return Resolution(text, status, best, alts, asks, pq, spans, notes)


def _asks(resolver, pq, ctx, fine, coarse) -> list[str]:
    g = resolver.g
    asks: list[str] = []
    if pq.po_box:
        asks.append("A PO box is not a physical location: share a building, street or landmark.")
    has_street = bool(ctx["street_spans"])
    has_area = bool(ctx["area_spans"])
    has_city = bool(ctx["city_spans"])
    if not (has_street or has_area or has_city or ctx["poi_spans"] or pq.landmark_span):
        asks.append("No UAE place name recognised: add an area (e.g. district) and the city.")
        return asks
    top = fine[0] if fine else (coarse[0] if coarse else None)
    if has_street and not ctx["hns"] and not ctx["poi_spans"]:
        asks.append("Add the building / house number.")
    if top is not None and has_street:
        multi = top.features.get("n_same_clusters", 0) > 1 or (
            top.features.get("n_groups", 0) > 1 and not has_area
        )
        if multi:
            opts = _district_options(g, ctx)
            if opts:
                asks.append("Which district? Possible: " + "; ".join(opts[:4]) + ".")
            else:
                asks.append("Several places match: add the district or a landmark.")
    if has_street and ctx["hns"] and fine and fine[0].tier == "interpolated":
        asks.append("That exact building number is not in the registry: please verify it.")
    if not has_street and has_area and not ctx["poi_spans"] and not pq.landmark_span:
        asks.append("Add a street name or a landmark to narrow it down.")
    if not has_city and top is not None and not (has_street and ctx["hns"] and not asks):
        asks.append("Add the city / emirate.")
    return asks


def _district_options(g, ctx) -> list[str]:
    from collections import Counter

    opts: Counter = Counter()
    for ss in ctx["street_spans"][:1]:
        ids = g.addr_by_street.get(ss.key, []) or g.addr_by_street.get(ss.sorted_key, [])
        for i in ids:
            a = g.addr[i]
            d = a[5] or a[4]
            if d:
                opts[f"{d}, {a[10]}"] += 1
    return [k for k, _ in opts.most_common(4)]


# ----------------------------------------------------------------------------- radii


def empirical_radii(errors_by_tier: dict[str, list[float]], q: float = 0.9) -> dict[str, float]:
    """90th-percentile distance error per tier: a distribution-free (conformal-style) radius."""
    out: dict[str, float] = {}
    for tier, errs in errors_by_tier.items():
        if len(errs) >= 30:
            out[tier] = max(25.0, float(np.quantile(np.array(errs), q)))
    return out
