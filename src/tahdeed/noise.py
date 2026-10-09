"""Synthetic free-text query generation with a documented noise model.

Queries are rendered from real gazetteer records (the truth), then degraded the ways real
users degrade addresses: dropped fields, language mixing, transliteration variants, typos,
abbreviations, Arabic-Indic digits, building keywords, reordering and missing commas.

The noise model is *ours*, not measured from real users: it is documented in
docs/EVALUATION.md as a limitation. It does, however, exercise each failure mode separately
so results can be reported per noise type.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field

from .gazetteer import Gazetteer
from .normalize import has_arabic

SPLITS = ("train", "calib", "dev", "sealed")


def split_of(key: str) -> str:
    """Deterministic district-level split: 50% train, 20% calibration, 20% dev, 10% sealed.

    ``dev`` is used freely while iterating. ``sealed`` is touched only for the v1.0 baseline
    and for the final report (see docs/PREDICTIONS.md).
    """
    b = zlib.crc32(key.encode("utf-8")) % 10
    return "train" if b < 5 else ("calib" if b < 7 else ("dev" if b < 9 else "sealed"))


@dataclass
class Query:
    text: str
    truth_kind: str  # "addr" | "poi"
    truth_idx: int
    lat: float
    lon: float
    noise: list[str] = field(default_factory=list)
    slice: str = "full"  # full | partial | no_hn
    split: str = "test"
    lang: str = "en"
    hidden: bool = False  # truth removed from the index at query time (coverage-hole test)


# ----------------------------------------------------------------------------- perturbations

# Consonant-changing transliteration variants (these defeat vowel-dropping skeletons).
_CONSONANT_VARIANTS = [
    ("kh", "k"), ("kh", "x"), ("gh", "g"), ("dh", "d"), ("dh", "th"), ("th", "t"),
    ("sh", "s"), ("q", "k"), ("q", "g"), ("j", "g"), ("j", "y"), ("z", "s"), ("ch", "sh"),
]  # fmt: skip
# Vowel-only variants (realistic, but the skeleton absorbs them).
_VOWEL_VARIANTS = [
    ("ee", "i"), ("ee", "ei"), ("ou", "u"), ("oo", "u"), ("aa", "a"), ("ah", "a"),
    ("iyah", "ia"), ("iyah", "iya"), ("ay", "ai"), ("ey", "ay"), ("e", "i"), ("u", "o"),
]  # fmt: skip


def _variant(word: str, rng: random.Random, table) -> tuple[str, bool]:
    opts = [(a, b) for a, b in table if a in word]
    if not opts:
        return word, False
    a, b = rng.choice(opts)
    return word.replace(a, b, 1), True


def perturb_translit(text: str, rng: random.Random, consonant: bool) -> tuple[str, bool]:
    words = text.split(" ")
    idx = [i for i, w in enumerate(words) if len(w) >= 4 and w.isalpha() and not has_arabic(w)]
    if not idx:
        return text, False
    i = rng.choice(idx)
    new, changed = _variant(
        words[i].lower(), rng, _CONSONANT_VARIANTS if consonant else _VOWEL_VARIANTS
    )
    if not changed:
        return text, False
    words[i] = new.capitalize()
    return " ".join(words), True


def typo(text: str, rng: random.Random) -> tuple[str, bool]:
    words = text.split(" ")
    idx = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
    if not idx:
        return text, False
    i = rng.choice(idx)
    w = words[i]
    p = rng.randrange(1, len(w) - 1)
    op = rng.choice(["del", "swap", "sub", "dup"])
    if op == "del":
        w = w[:p] + w[p + 1 :]
    elif op == "swap":
        w = w[:p] + w[p + 1] + w[p] + w[p + 2 :]
    elif op == "dup":
        w = w[:p] + w[p] + w[p:]
    else:
        pool = "arstnlmdbk" if not has_arabic(w) else "ابتنلمرس"
        w = w[:p] + rng.choice(pool) + w[p + 1 :]
    words[i] = w
    return " ".join(words), True


_ABBR = {"Street": "St", "Road": "Rd", "Avenue": "Ave", "Boulevard": "Blvd", "Lane": "Ln"}
_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def abbreviate(text: str) -> tuple[str, bool]:
    out, ch = [], False
    for w in text.split(" "):
        if w in _ABBR:
            out.append(_ABBR[w])
            ch = True
        else:
            out.append(w)
    return " ".join(out), ch


# ----------------------------------------------------------------------------- rendering


def _pick(rng: random.Random, en: str | None, ar: str | None, lang: str) -> str | None:
    if lang == "en":
        return en or ar
    if lang == "ar":
        return ar or en
    return rng.choice([x for x in (en, ar) if x] or [None])


def render_address(a: tuple, rng: random.Random) -> tuple[str, list[str], str, str]:
    """Render one address row (gazetteer tuple) as noisy free text.

    Returns (text, noise tags, slice name, language label).
    """
    tags: list[str] = []
    r = rng.random()
    lang = "en" if r < 0.55 else ("ar" if r < 0.80 else "mixed")
    tags.append(f"lang_{lang}")

    hn = a[1]
    street = _pick(rng, a[3], a[2], lang)
    district = _pick(rng, a[5], a[4], lang)
    city = _pick(rng, a[10], a[9], lang)
    postcode = a[11]

    slice_name = "full"
    drop_hn = rng.random() < 0.10
    if drop_hn:
        slice_name = "no_hn"
        tags.append("drop_hn")
    keep_district = rng.random() < 0.65
    keep_city = rng.random() < 0.70
    if not keep_district:
        tags.append("drop_district")
    if not keep_city:
        tags.append("drop_city")
    if (not keep_district or not keep_city) and slice_name == "full":
        slice_name = "partial"
    use_pc = bool(postcode) and rng.random() < 0.12

    def render_field(v: str | None, is_name: bool) -> str | None:
        if not v:
            return v
        if not has_arabic(v) and is_name:
            if rng.random() < 0.30:
                v2, ch = perturb_translit(v, rng, consonant=True)
                if ch:
                    tags.append("translit_consonant")
                    v = v2
            if rng.random() < 0.25:
                v2, ch = perturb_translit(v, rng, consonant=False)
                if ch:
                    tags.append("translit_vowel")
                    v = v2
            if rng.random() < 0.20:
                v2, ch = typo(v, rng)
                if ch:
                    tags.append("typo")
                    v = v2
            if rng.random() < 0.35:
                v2, ch = abbreviate(v)
                if ch:
                    tags.append("abbrev")
                    v = v2
        elif has_arabic(v) and is_name and rng.random() < 0.15:
            v2, ch = typo(v, rng)
            if ch:
                tags.append("typo")
                v = v2
        return v

    street = render_field(street, True)
    district = render_field(district, True)

    hn_txt = None
    if not drop_hn and hn:
        hn_txt = hn
        if rng.random() < 0.25:
            kw = (
                rng.choice(["Villa", "Building", "Bldg", "No."])
                if lang != "ar"
                else rng.choice(["فيلا", "مبنى", "رقم"])
            )
            hn_txt = f"{kw} {hn}"
            tags.append("hn_keyword")

    parts_street = " ".join(x for x in (hn_txt, street) if x)
    if hn_txt and rng.random() < 0.12:
        parts_street = " ".join(x for x in (street, hn_txt) if x)
        tags.append("hn_after_street")
    parts = [parts_street]
    if keep_district and district:
        parts.append(district)
    if keep_city and city:
        parts.append(city)
    if use_pc:
        parts.append(str(postcode))
        tags.append("postcode")
    if rng.random() < 0.12 and len(parts) > 2:
        parts[1], parts[2] = parts[2], parts[1]
        tags.append("reorder")
    sep = ", " if rng.random() < 0.6 else " "
    if sep == " ":
        tags.append("no_commas")
    text = sep.join(p for p in parts if p)
    if lang in ("ar", "mixed") and rng.random() < 0.7:
        text = text.translate(_ARABIC_INDIC)
        tags.append("arabic_digits")
    if rng.random() < 0.2:
        text = text.lower()
        tags.append("lowercase")
    return text, tags, slice_name, lang


def make_address_queries(
    g: Gazetteer,
    n: int,
    split: str,
    seed: int = 0,
    structured_only: bool = True,
    hole_rate: float = 0.0,
) -> list[Query]:
    """Sample ``n`` queries whose truth address lies in a district assigned to ``split``."""
    rng = random.Random(f"{seed}-{split}")
    ids = [
        i
        for i, a in enumerate(g.addr)
        if (a[15] or not structured_only)
        and split_of(f"{a[8]}|{a[5] or a[4] or ''}") == split
        and a[1]
        and (a[2] or a[3])
    ]
    rng.shuffle(ids)
    out: list[Query] = []
    for i in ids[:n]:
        a = g.addr[i]
        text, tags, sl, lang = render_address(a, rng)
        hidden = rng.random() < hole_rate
        if hidden:
            tags.append("hidden_truth")
        out.append(Query(text, "addr", i, a[12], a[13], tags, sl, split, lang, hidden))
    return out


def make_poi_queries(g: Gazetteer, n: int, split: str, seed: int = 0) -> list[Query]:
    """Dubai-style POI queries: name + (street) + city, truth = POI location."""
    rng = random.Random(f"{seed}-poi-{split}")
    ids = [
        i
        for i, p in enumerate(g.pois)
        if p[5] and (p[3] or p[2]) and p[6] in ("dubai", "sharjah", "ajman")
        and split_of(f"poi|{p[6]}|{p[5]}") == split
    ]  # fmt: skip
    rng.shuffle(ids)
    out: list[Query] = []
    for i in ids[:n]:
        p = g.pois[i]
        tags: list[str] = []
        lang = rng.choice(["en", "en", "ar"]) if p[2] and p[3] else ("ar" if p[2] else "en")
        name = (p[2] if lang == "ar" else p[3]) or p[1]
        if not has_arabic(name) and rng.random() < 0.25:
            name, ch = typo(name, rng)
            if ch:
                tags.append("typo")
        parts = [name]
        if rng.random() < 0.8:
            parts.append(p[5])
        else:
            tags.append("drop_street")
        ck, _ = g.city_name(p[6])
        if rng.random() < 0.7:
            parts.append(ck)
        else:
            tags.append("drop_city")
        out.append(Query(", ".join(parts), "poi", i, p[8], p[9], tags, "poi", split, lang))
    return out
