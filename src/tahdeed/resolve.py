"""Tiered address resolution.

Pipeline: parse -> gazetteer-driven n-gram name matching -> tiered candidate generation
(address, POI, interpolated, landmark, street+area, street, area, city) -> features for the
ranker/calibrator -> decision (resolved / approximate / ambiguous / unresolved).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz, process

from .gazetteer import Gazetteer, hn_int, norm_hn
from .geo import CITY_BY_KEY, haversine_m, haversine_np
from .normalize import STOPWORDS, STREET_TYPES, coarse_key, skeleton_tokens, strip_articles
from .parse import RELATION_RADIUS_M, NumberRef, ParsedQuery, parse

FINE_TIERS = ("address", "poi", "interpolated", "landmark")
TIER_ORDER = ("address", "poi", "interpolated", "landmark", "street_area", "street", "area", "city")

# Starting radii (metres) used until calibration provides empirical 90% radii per tier.
DEFAULT_RADIUS_M = {
    "address": 30.0,
    "poi": 60.0,
    "interpolated": 150.0,
    "landmark": 250.0,
    "street_area": 1200.0,
    "street": 4000.0,
    "area": 2500.0,
    "city": 15000.0,
}

MAX_NGRAM = 8
FUZZY_CUTOFF = 86.0


# ----------------------------------------------------------------------------- data types


@dataclass
class Span:
    start: int
    end: int  # exclusive
    key: str
    sorted_key: str
    streets: bool = False
    areas: list[int] = field(default_factory=list)
    pois: list[int] = field(default_factory=list)
    city: str | None = None
    quality: float = 1.0
    fuzzy: bool = False
    has_type: bool = False
    text: str = ""

    @property
    def n(self) -> int:
        return self.end - self.start


@dataclass
class Candidate:
    tier: str
    lat: float
    lon: float
    radius_m: float
    label: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    p50: float | None = None  # calibrated P(within 50 m); set by the ranker
    p_valid: float | None = None  # calibrated P(candidate is correct at its own tier)
    ref: tuple[str, int] | None = None  # ("addr"|"street"|"area"|"poi", row index)


@dataclass
class Resolution:
    query: str
    status: str  # resolved | approximate | ambiguous | unresolved
    best: Candidate | None
    alternatives: list[Candidate]
    asks: list[str]
    parsed: ParsedQuery
    spans: list[Span]
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- span matching


def _span_keys(tokens: list[str]) -> tuple[str, str]:
    toks = [t for t in tokens if t not in STOPWORDS and t not in STREET_TYPES]
    sk = skeleton_tokens(strip_articles(toks))
    return "".join(sk), "".join(sorted(sk))


def find_spans(g: Gazetteer, pq: ParsedQuery, indices: list[int] | None = None) -> list[Span]:
    """All name matches for the (unconsumed) tokens, as non-overlapping spans."""
    tokens = pq.tokens
    idx = pq.body_indices() if indices is None else indices
    # contiguous runs within a segment
    runs: list[list[int]] = []
    for i in idx:
        if runs and runs[-1][-1] == i - 1 and pq.seg_of[runs[-1][-1]] == pq.seg_of[i]:
            runs[-1].append(i)
        else:
            runs.append([i])

    exact: list[Span] = []
    for run in runs:
        for a in range(len(run)):
            for b in range(a + 1, min(len(run), a + MAX_NGRAM) + 1):
                toks = tokens[run[a] : run[b - 1] + 1]
                if all(t in STOPWORDS or t in STREET_TYPES for t in toks):
                    continue
                key, skey = _span_keys(toks)
                if not key:
                    continue
                has_type = any(t in STREET_TYPES for t in toks)
                if key.isdigit() and not has_type:
                    continue
                sp = Span(run[a], run[b - 1] + 1, key, skey, has_type=has_type, text=" ".join(toks))
                hit = False
                for k in (key, skey):
                    if g.has_street_key(k):
                        sp.streets = True
                        hit = True
                    if k in g.area_by_key:
                        sp.areas = sorted(set(sp.areas) | set(g.area_by_key[k]))
                        hit = True
                    if k in g.poi_by_key:
                        sp.pois = sorted(set(sp.pois) | set(g.poi_by_key[k]))
                        hit = True
                    if k in g.city_by_key_alias:
                        sp.city = g.city_by_key_alias[k]
                        hit = True
                if hit:
                    exact.append(sp)

    # consonant-class (coarse) matches for n-grams without an exact hit: cheap dict lookups
    exact_ranges = {(s.start, s.end) for s in exact}
    approx: list[Span] = []
    for run in runs:
        for a in range(len(run)):
            for b in range(a + 1, min(len(run), a + MAX_NGRAM) + 1):
                if (run[a], run[b - 1] + 1) in exact_ranges:
                    continue
                toks = tokens[run[a] : run[b - 1] + 1]
                if all(t in STOPWORDS or t in STREET_TYPES for t in toks):
                    continue
                key, _ = _span_keys(toks)
                if len(key) < 4 or key.isdigit():
                    continue
                has_type = any(t in STREET_TYPES for t in toks)
                sp = _approx_span(g, run[a], run[b - 1] + 1, key, has_type, " ".join(toks))
                if sp is not None:
                    approx.append(sp)

    chosen = _select(exact + approx)
    # fuzzy (edit-distance) pass over runs not covered yet
    covered = {i for s in chosen for i in range(s.start, s.end)}
    fuzzy: list[Span] = []
    for run in runs:
        free = [i for i in run if i not in covered]
        sub: list[list[int]] = []
        for i in free:
            if sub and sub[-1][-1] == i - 1:
                sub[-1].append(i)
            else:
                sub.append([i])
        for sr in sub:
            for a in range(len(sr)):
                for b in range(a + 1, min(len(sr), a + 4) + 1):
                    toks = tokens[sr[a] : sr[b - 1] + 1]
                    if all(t in STOPWORDS or t in STREET_TYPES for t in toks):
                        continue
                    key, _ = _span_keys(toks)
                    if len(key) < 5 or key.isdigit():
                        continue
                    has_type = any(t in STREET_TYPES for t in toks)
                    sp = _fuzzy_span(g, sr[a], sr[b - 1] + 1, key, has_type, " ".join(toks))
                    if sp is not None:
                        fuzzy.append(sp)
    chosen = _select(exact + approx + fuzzy)
    return sorted(chosen, key=lambda s: s.start)


def _attach(g: Gazetteer, sp: Span, kind: str, k: str) -> None:
    if kind == "street":
        sp.streets = True
        sp.key = k
    elif kind == "area":
        sp.areas = sorted(set(sp.areas) | set(g.area_by_key[k]))
    else:
        sp.pois = sorted(set(sp.pois) | set(g.poi_by_key[k]))


def _approx_span(g, start, end, key, has_type, text) -> Span | None:
    """Coarse-key lookup: tolerates consonant-class transliteration variants (k/kh/q, s/sh...)."""
    ck = coarse_key(key)
    sp = Span(start, end, key, key, has_type=has_type, fuzzy=True, text=text)
    best = 0.0
    for table, kind in (
        (g.street_coarse, "street"),
        (g.area_coarse, "area"),
        (g.poi_coarse, "poi"),
    ):
        keys = table.get(ck)
        if not keys:
            continue
        k = max(keys, key=lambda x: fuzz.ratio(key, x))
        r = fuzz.ratio(key, k)
        if r < 70:
            continue
        best = max(best, r)
        _attach(g, sp, kind, k)
    if not best:
        return None
    sp.quality = 0.9 * best / 100.0
    return sp


def _fuzzy_span(g, start, end, key, has_type, text) -> Span | None:
    sp = Span(start, end, key, key, has_type=has_type, fuzzy=True, text=text)
    best = 0.0
    for lst, kind in (
        (g.street_key_list, "street"),
        (g.area_key_list, "area"),
        (g.poi_key_list, "poi"),
    ):
        m = process.extractOne(key, lst, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF)
        if not m:
            continue
        k, score, _ = m
        best = max(best, score)
        _attach(g, sp, kind, k)
    if not best:
        return None
    sp.quality = 0.9 * best / 100.0
    return sp


def _select(spans: list[Span]) -> list[Span]:
    """Greedy non-overlapping selection by explained name mass (key length x match quality)."""
    spans = sorted(spans, key=lambda s: (-len(s.key) * s.quality, -s.n, s.start))
    taken: set[int] = set()
    out: list[Span] = []
    for s in spans:
        rng = set(range(s.start, s.end))
        if rng & taken:
            continue
        out.append(s)
        taken |= rng
    return out


# ----------------------------------------------------------------------------- resolver


class Resolver:
    def __init__(self, g: Gazetteer, ranker=None, radii: dict[str, float] | None = None):
        self.g = g
        self.ranker = ranker  # object with .score(list[Candidate]) -> None (sets p50)
        self.radii = dict(DEFAULT_RADIUS_M)
        if radii:
            self.radii.update(radii)

    # ------------------------------------------------------------------ public
    def resolve(
        self,
        text: str,
        hide_addr: frozenset[int] | set[int] = frozenset(),
        hide_poi: frozenset[int] | set[int] = frozenset(),
    ) -> Resolution:
        return self._resolve(text, hide_addr, hide_poi, decide=True)

    def _candidates(self, text, hide_addr, hide_poi) -> list[Candidate]:
        return self._resolve(text, hide_addr, hide_poi, decide=False)

    def _resolve(self, text, hide_addr, hide_poi, decide: bool):
        g = self.g
        pq = parse(text)
        spans = find_spans(g, pq)
        notes: list[str] = []
        if pq.po_box:
            notes.append("PO box is a mailing location, not a physical one: ignored for geocoding")
        if pq.makani:
            notes.append(f"Makani number {pq.makani} recognised (not resolvable offline)")

        # A name that is both a street key and an area/city name, written without a street-type
        # word ("Al Khalidiyah Abu Dhabi"), is an area/city, not a street.
        for sp in spans:
            if sp.streets and (sp.areas or sp.city) and not sp.has_type:
                sp.streets = False

        # landmark phrase (matched separately)
        lm_spans: list[Span] = []
        if pq.landmark_span:
            a, b = pq.landmark_span
            lm_spans = find_spans(g, pq, indices=list(range(a, b)))

        cities = {s.city for s in spans if s.city}
        cities |= {s.city for s in lm_spans if s.city}
        street_spans = [s for s in spans if s.streets]
        area_spans = [s for s in spans if s.areas and not (s.streets and s.n > 1 and s.has_type)]
        poi_spans = [s for s in spans if s.pois]
        city_spans = [s for s in spans if s.city]

        hns = self._house_numbers(pq, spans)
        covered_tokens = {i for s in spans for i in range(s.start, s.end)}
        body = pq.body_indices()
        unexplained = [i for i in body if i not in covered_tokens and not _is_filler(pq.tokens[i])]
        ctx = {
            "pq": pq,
            "cities": cities,
            "street_spans": street_spans,
            "area_spans": area_spans,
            "poi_spans": poi_spans,
            "city_spans": city_spans,
            "hns": hns,
            "n_body": len(body),
            "n_unexplained": len(unexplained),
            "hide_addr": hide_addr,
            "hide_poi": hide_poi,
        }

        cands: list[Candidate] = []
        cands += self._address_candidates(ctx)
        cands += self._poi_candidates(ctx)
        cands += self._landmark_candidates(ctx, lm_spans)
        cands += self._area_candidates(ctx)
        cands += self._city_candidates(ctx)

        if not decide:
            return cands
        if self.ranker:
            self.ranker.score(cands)
        res = self._decide(text, pq, spans, cands, ctx, notes)
        if res.best is not None:
            self._apply_radius(res.best)
        return res

    def resolve_candidates(self, text, hide_addr=frozenset(), hide_poi=frozenset()):
        """Candidates before ranking/decision (used to build training data)."""
        saved, self.ranker = self.ranker, None
        try:
            return self._candidates(text, hide_addr, hide_poi)
        finally:
            self.ranker = saved

    def _apply_radius(self, c: Candidate) -> None:
        r = getattr(self.ranker, "radii", None) or {}
        if c.tier in r and c.tier not in FINE_TIERS:
            c.radius_m = float(r[c.tier])

    # ------------------------------------------------------------------ helpers
    def _house_numbers(self, pq: ParsedQuery, spans: list[Span]) -> list[str]:
        covered = {i for s in spans if s.streets and s.has_type for i in range(s.start, s.end)}
        keyed: list[NumberRef] = []
        leading: list[NumberRef] = []
        other: list[NumberRef] = []
        for nr in pq.numbers:
            if nr.pos in covered:
                continue
            if nr.keyword:
                keyed.append(nr)
            elif nr.adjacent_type:
                continue
            elif nr.leading:
                leading.append(nr)
            else:
                other.append(nr)
        out: list[str] = []
        for nr in keyed + leading + other:
            h = norm_hn(nr.value)
            if h and h not in out and len(h) <= 6:
                out.append(h)
        return out[:3]

    def _filter_ids(self, ids: list[int], ctx: dict, kind: str = "addr") -> list[int]:
        hide = ctx["hide_addr"] if kind == "addr" else ctx["hide_poi"]
        return [i for i in ids if i not in hide] if hide else ids

    # ------------------------------------------------------------------ address-level
    def _address_candidates(self, ctx: dict) -> list[Candidate]:
        g = self.g
        out: list[Candidate] = []
        area_keys = self._area_key_set(ctx)
        cities = ctx["cities"]
        for ss in sorted(ctx["street_spans"], key=lambda s: -(s.n * s.quality))[:2]:
            keys = [k for k in {ss.key, ss.sorted_key} if g.has_street_key(k)]
            ids: list[int] = []
            for k in keys:
                ids += g.addr_by_street.get(k, [])
            ids = self._filter_ids(sorted(set(ids)), ctx)
            seg_ids: list[int] = []
            for k in keys:
                seg_ids += g.street_by_key.get(k, [])
            seg_ids = sorted(set(seg_ids))

            def city_ok(i: int) -> bool:
                return not cities or g.addr[i][8] in cities

            ids_c = [i for i in ids if city_ok(i)]
            city_consistent = 1 if (cities and ids_c) else (-1 if (cities and ids) else 0)
            base = ids_c if ids_c else ids
            ids_a = [i for i in base if g.addr_area_keys[i] & area_keys] if area_keys else []
            area_consistent = 1 if ids_a else (-1 if area_keys and base else 0)
            pool = ids_a if ids_a else base

            groups = Counter((g.addr[i][8], g.addr[i][5] or g.addr[i][4]) for i in pool)
            base_feat = {
                "street_quality": ss.quality,
                "street_fuzzy": int(ss.fuzzy),
                "street_tokens": ss.n,
                "street_key_len": len(ss.key),
                "street_has_type": int(ss.has_type),
                "city_consistent": city_consistent,
                "area_consistent": area_consistent,
                "n_street_addr": len(pool),
                "n_groups": len(groups),
                "n_body": ctx["n_body"],
                "n_unexplained": ctx["n_unexplained"],
                "has_landmark": int(ctx["pq"].relation is not None),
                "has_hn": int(bool(ctx["hns"])),
            }
            produced = False
            for h in ctx["hns"][:2]:
                ex: list[int] = []
                for k in keys:
                    ex += g.addr_by_street_hn.get((k, h), [])
                ex = self._filter_ids(sorted(set(ex)), ctx)
                if not ex:
                    continue
                exc = [i for i in ex if city_ok(i)] or ex
                exa = [i for i in exc if g.addr_area_keys[i] & area_keys] if area_keys else []
                pick = exa or exc
                cluster = len({(g.addr[i][8], g.addr[i][5] or g.addr[i][4]) for i in pick})
                for i in pick[:4]:
                    a = g.addr[i]
                    f = dict(base_feat)
                    f.update(
                        n_same=len(pick),
                        n_same_clusters=cluster,
                        hn_rank=ctx["hns"].index(h),
                        postcode_match=0,
                    )
                    out.append(
                        Candidate(
                            "address",
                            a[12],
                            a[13],
                            self.radii["address"],
                            label=_addr_label(a),
                            evidence=_ev(ss, ctx, h, "exact"),
                            features=f,
                            ref=("addr", i),
                        )  # fmt: skip
                    )
                produced = True
            if produced:
                continue
            # interpolation between neighbouring numbers (single district only)
            if ctx["hns"] and pool:
                cand = self._interpolate(pool, ctx["hns"][0], ss, base_feat, ctx)
                if cand:
                    out.append(cand)
            # street (+area) only
            out += self._street_candidates(
                pool, seg_ids, ss, area_spans=ctx["area_spans"], base_feat=base_feat, ctx=ctx
            )
        return out

    def _area_key_set(self, ctx: dict) -> set[str]:
        g = self.g
        keys: set[str] = set()
        for s in ctx["area_spans"]:
            keys.add(s.key)
            keys.add(s.sorted_key)
            for ai in s.areas:
                a = g.areas[ai]
                from .gazetteer import keys_of

                keys |= keys_of(a[1], a[2])
        return keys

    def _interpolate(self, pool, h: str, ss: Span, base_feat: dict, ctx: dict) -> Candidate | None:
        g = self.g
        n = hn_int(h)
        if n is None:
            return None
        clusters = {(g.addr[i][8], g.addr[i][5] or g.addr[i][4]) for i in pool}
        if len(clusters) != 1:
            return None
        nums = [(hn_int(g.addr_hn[i]), i) for i in pool if hn_int(g.addr_hn[i]) is not None]
        same_par = [(v, i) for v, i in nums if v % 2 == n % 2] or nums
        lower = [(v, i) for v, i in same_par if v < n]
        upper = [(v, i) for v, i in same_par if v > n]
        lo = max(lower) if lower else None
        up = min(upper) if upper else None
        if lo and up:
            t = (n - lo[0]) / (up[0] - lo[0])
            lat = g.addr_lat[lo[1]] + t * (g.addr_lat[up[1]] - g.addr_lat[lo[1]])
            lon = g.addr_lon[lo[1]] + t * (g.addr_lon[up[1]] - g.addr_lon[lo[1]])
            gap = up[0] - lo[0]
            span_m = haversine_m(g.addr_lat[lo[1]], g.addr_lon[lo[1]], g.addr_lat[up[1]],
                                 g.addr_lon[up[1]])  # fmt: skip
            kind = "between"
            ref_i = lo[1] if t < 0.5 else up[1]
        else:
            nb = lo or up
            if nb is None:
                return None
            lat, lon = g.addr_lat[nb[1]], g.addr_lon[nb[1]]
            gap = abs(nb[0] - n)
            span_m = 0.0
            kind = "extrapolated"
            ref_i = nb[1]
        f = dict(base_feat)
        f.update(gap=gap, span_m=span_m, between=int(kind == "between"), n_same=0, n_same_clusters=0,
                 hn_rank=0, postcode_match=0)  # fmt: skip
        lab = _addr_label(g.addr[ref_i])
        lab["building"] = h
        return Candidate("interpolated", float(lat), float(lon), self.radii["interpolated"],
                         label=lab, evidence=_ev(ss, ctx, h, kind), features=f,
                         ref=("addr", ref_i))  # fmt: skip

    def _street_candidates(self, pool, seg_ids, ss: Span, area_spans, base_feat, ctx):
        """Street-level candidates, one per city the street name occurs in (top 3)."""
        g = self.g
        cities = ctx["cities"]
        out: list[Candidate] = []
        if pool:
            by_city: dict[str, list[int]] = {}
            for i in pool:
                by_city.setdefault(g.addr[i][8], []).append(i)
            groups = sorted(by_city.items(), key=lambda kv: -len(kv[1]))[:3]
            for _ck, ids in groups:
                lat = float(np.mean(g.addr_lat[ids]))
                lon = float(np.mean(g.addr_lon[ids]))
                d = haversine_np(lat, lon, g.addr_lat[ids], g.addr_lon[ids])
                spread = float(np.percentile(d, 90))
                i0 = ids[int(np.argmin(d))]
                lab = _addr_label(g.addr[i0])
                lab.pop("building", None)
                tier = "street_area" if base_feat["area_consistent"] == 1 else "street"
                f = dict(base_feat)
                f.update(
                    spread_m=spread, n_cities=len(by_city), group_size=len(ids),
                    group_frac=len(ids) / len(pool), n_same=0, n_same_clusters=len(by_city),
                    hn_rank=0, postcode_match=0,
                )  # fmt: skip
                out.append(
                    Candidate(
                        tier,
                        lat,
                        lon,
                        max(self.radii[tier], spread),
                        label=lab,
                        evidence=_ev(ss, ctx, None, tier),
                        features=f,
                        ref=("addr", i0),
                    )  # fmt: skip
                )
        elif seg_ids:
            by_city = {}
            for sid in seg_ids:
                by_city.setdefault(g.streets[sid][5], []).append(sid)
            if cities:
                by_city = {k: v for k, v in by_city.items() if k in cities} or by_city
            groups = sorted(by_city.items(), key=lambda kv: -len(kv[1]))[:3]
            for _ck, segs in groups:
                tier = "street"
                if area_spans:
                    a = g.areas[area_spans[0].areas[0]]
                    dd = haversine_np(a[5], a[6], g.street_lat[segs], g.street_lon[segs])
                    segs = [segs[int(np.argmin(dd))]]
                    tier = "street_area"
                lat = float(np.mean(g.street_lat[segs]))
                lon = float(np.mean(g.street_lon[segs]))
                d = haversine_np(lat, lon, g.street_lat[segs], g.street_lon[segs])
                spread = float(np.percentile(d, 90)) if len(d) > 1 else 300.0
                s0 = g.streets[segs[0]]
                lab = {
                    "street_en": s0[3],
                    "street_ar": s0[2] or (s0[1] if _has_ar(s0[1]) else None),
                    "city_key": s0[5],
                }
                f = dict(base_feat)
                f.update(
                    spread_m=spread, n_cities=len(by_city), group_size=len(segs),
                    group_frac=len(segs) / max(1, len(seg_ids)), n_same=0,
                    n_same_clusters=len(by_city), hn_rank=0, postcode_match=0,
                )  # fmt: skip
                out.append(
                    Candidate(
                        tier,
                        lat,
                        lon,
                        max(self.radii[tier], spread),
                        label=lab,
                        evidence=_ev(ss, ctx, None, tier),
                        features=f,
                        ref=None,
                    )  # fmt: skip
                )
        return out

    # ------------------------------------------------------------------ POI / landmark
    def _poi_candidates(self, ctx: dict) -> list[Candidate]:
        g = self.g
        out: list[Candidate] = []
        cities = ctx["cities"]
        street_keys = {k for s in ctx["street_spans"] for k in (s.key, s.sorted_key)}
        area_keys = self._area_key_set(ctx)
        from .gazetteer import keys_of

        for ps in sorted(ctx["poi_spans"], key=lambda s: -(s.n * s.quality))[:2]:
            ids = self._filter_ids(ps.pois, ctx, "poi")
            if not ids:
                continue
            ids_c = [i for i in ids if not cities or g.pois[i][6] in cities]
            city_consistent = 1 if (cities and ids_c) else (-1 if cities else 0)
            ids = ids_c or ids
            scored = []
            for i in ids:
                p = g.pois[i]
                st_ok = 0
                if street_keys and p[5]:
                    st_ok = 1 if (keys_of(p[5]) & street_keys) else -1
                scored.append((st_ok, i))
            scored.sort(key=lambda t: -t[0])
            top = scored[:3]
            names = Counter()
            for _, i in scored:
                names[(g.pois[i][6])] += 1
            for st_ok, i in top:
                p = g.pois[i]
                f = {
                    "poi_quality": ps.quality,
                    "poi_fuzzy": int(ps.fuzzy),
                    "poi_tokens": ps.n,
                    "poi_key_len": len(ps.key),
                    "n_poi_same": len(ids),
                    "poi_street_consistent": st_ok,
                    "city_consistent": city_consistent,
                    "area_given": int(bool(area_keys)),
                    "has_street": int(bool(street_keys)),
                    "has_hn": int(bool(ctx["hns"])),
                    "n_body": ctx["n_body"],
                    "n_unexplained": ctx["n_unexplained"],
                    "poi_is_whole_query": int(ps.n >= ctx["n_body"]),
                    "n_same_clusters": len(names),
                }
                ck = CITY_BY_KEY.get(p[6])
                out.append(
                    Candidate(
                        "poi",
                        p[8],
                        p[9],
                        self.radii["poi"],
                        label={
                            "name_en": p[3],
                            "name_ar": p[2],
                            "poi_kind": p[4],
                            "street": p[5],
                            "city_en": ck.en if ck else p[6],
                            "city_ar": ck.ar if ck else None,
                        },
                        evidence={"matched": ps.text, "fuzzy": ps.fuzzy},
                        features=f,
                        ref=("poi", i),
                    )  # fmt: skip
                )
        return out

    def _landmark_candidates(self, ctx: dict, lm_spans: list[Span]) -> list[Candidate]:
        g = self.g
        pq = ctx["pq"]
        if not pq.relation or not lm_spans:
            return []
        out: list[Candidate] = []
        rel_r = float(RELATION_RADIUS_M.get(pq.relation, 250))
        anchor = self._context_anchor(ctx)
        for ls in sorted(lm_spans, key=lambda s: -(s.n * s.quality))[:1]:
            targets: list[tuple[float, float, str, dict, int, str]] = []
            for i in ls.pois:
                p = g.pois[i]
                targets.append((p[8], p[9], "poi", {"name_en": p[3], "name_ar": p[2]}, i, p[6]))
            for ai in ls.areas[:6]:
                a = g.areas[ai]
                targets.append((a[5], a[6], "area", {"name_en": a[2], "name_ar": a[1]}, ai, a[4]))
            if not targets:
                continue
            cities = ctx["cities"]
            if cities:
                tc = [t for t in targets if t[5] in cities]
                targets = tc or targets
            if anchor:
                targets.sort(key=lambda t: haversine_m(anchor[0], anchor[1], t[0], t[1]))
            n_inst = len(targets)
            for t in targets[:2]:
                dist = haversine_m(anchor[0], anchor[1], t[0], t[1]) if anchor else -1.0
                f = {
                    "lm_quality": ls.quality, "lm_fuzzy": int(ls.fuzzy), "lm_tokens": ls.n,
                    "lm_key_len": len(ls.key),
                    "lm_instances": n_inst, "lm_is_area": int(t[2] == "area"),
                    "anchor_dist_m": dist, "relation_radius": rel_r,
                    "n_body": ctx["n_body"], "n_unexplained": ctx["n_unexplained"],
                    "has_anchor": int(anchor is not None), "n_same_clusters": n_inst,
                }  # fmt: skip
                out.append(
                    Candidate(
                        "landmark",
                        t[0],
                        t[1],
                        max(rel_r, self.radii["landmark"] * 0.3),
                        label={**t[3], "relation": pq.relation},
                        evidence={"matched": ls.text, "relation": pq.relation},
                        features=f,
                        ref=(t[2], t[4]),
                    )  # fmt: skip
                )
        return out

    def _context_anchor(self, ctx: dict) -> tuple[float, float] | None:
        """Where the rest of the address points to (to choose between same-name landmarks)."""
        g = self.g
        for ss in ctx["street_spans"]:
            ids = g.addr_by_street.get(ss.key, []) or g.addr_by_street.get(ss.sorted_key, [])
            if ids:
                return float(np.mean(g.addr_lat[ids])), float(np.mean(g.addr_lon[ids]))
            segs = g.street_by_key.get(ss.key, [])
            if segs:
                return float(np.mean(g.street_lat[segs])), float(np.mean(g.street_lon[segs]))
        for s in ctx["area_spans"]:
            a = g.areas[s.areas[0]]
            return a[5], a[6]
        for c in ctx["cities"]:
            cc = CITY_BY_KEY.get(c)
            if cc:
                return cc.lat, cc.lon
        return None

    # ------------------------------------------------------------------ area / city
    def _area_candidates(self, ctx: dict) -> list[Candidate]:
        g = self.g
        out: list[Candidate] = []
        cities = ctx["cities"]
        from .gazetteer import keys_of

        for s in sorted(ctx["area_spans"], key=lambda s: -(s.n * s.quality))[:2]:
            ids = [i for i in s.areas if not cities or g.areas[i][4] in cities] or s.areas
            # prefer districts (derived from addresses) with more members, then place features
            ids = sorted(ids, key=lambda i: -g.areas[i][8])[:3]
            for i in ids:
                a = g.areas[i]
                ck = CITY_BY_KEY.get(a[4])
                f = {
                    "area_quality": s.quality, "area_fuzzy": int(s.fuzzy), "area_tokens": s.n,
                    "area_key_len": len(s.key),
                    "area_instances": len(s.areas), "area_n": a[8], "area_radius": a[7],
                    "city_consistent": 1 if cities and a[4] in cities else (0 if not cities else -1),
                    "n_body": ctx["n_body"], "n_unexplained": ctx["n_unexplained"],
                    "n_same_clusters": len(s.areas),
                }  # fmt: skip
                out.append(
                    Candidate(
                        "area",
                        a[5],
                        a[6],
                        max(self.radii["area"] * 0.4, float(a[7])),
                        label={
                            "area_en": a[2],
                            "area_ar": a[1],
                            "kind": a[3],
                            "city_en": ck.en if ck else a[4],
                            "city_ar": ck.ar if ck else None,
                        },
                        evidence={
                            "matched": s.text,
                            "fuzzy": s.fuzzy,
                            "area_keys": sorted(keys_of(a[1], a[2])),
                        },
                        features=f,
                        ref=("area", i),
                    )  # fmt: skip
                )
        return out

    def _city_candidates(self, ctx: dict) -> list[Candidate]:
        out: list[Candidate] = []
        for s in ctx["city_spans"][:1]:
            c = CITY_BY_KEY.get(s.city or "")
            if not c:
                continue
            f = {"n_body": ctx["n_body"], "n_unexplained": ctx["n_unexplained"],
                 "n_same_clusters": 1}  # fmt: skip
            out.append(
                Candidate(
                    "city",
                    c.lat,
                    c.lon,
                    self.radii["city"],
                    label={
                        "city_key": c.key,
                        "city_en": c.en,
                        "city_ar": c.ar,
                        "emirate": c.emirate,
                    },
                    evidence={"matched": s.text},
                    features=f,
                    ref=None,
                )  # fmt: skip
            )
        return out

    # ------------------------------------------------------------------ decision
    def _decide(self, text, pq, spans, cands, ctx, notes) -> Resolution:
        from .calibrate import decide  # local import: calibrate depends on resolve types

        return decide(self, text, pq, spans, cands, ctx, notes)


# ----------------------------------------------------------------------------- utilities


def _has_ar(s: str | None) -> bool:
    from .normalize import has_arabic

    return bool(s and has_arabic(s))


def _is_filler(tok: str) -> bool:
    return tok in STOPWORDS or tok in STREET_TYPES or tok.isdigit()


def _ev(ss: Span, ctx: dict, hn: str | None, how: str) -> dict:
    return {
        "street_matched": ss.text,
        "street_fuzzy": ss.fuzzy,
        "house_number": hn,
        "how": how,
        "keys": sorted({ss.key, ss.sorted_key}),
    }


def _addr_label(a: tuple) -> dict:
    return {
        "building": a[1],
        "street_ar": a[2],
        "street_en": a[3],
        "district_ar": a[4],
        "district_en": a[5],
        "subdistrict_ar": a[6],
        "subdistrict_en": a[7],
        "city_key": a[8],
        "city_ar": a[9],
        "city_en": a[10],
        "postcode": a[11],
    }
