"""Query parsing: pull out the parts of an address that are *not* place names.

Names (streets, districts, cities, landmarks) are found later by gazetteer-driven n-gram
lookup, which copes far better with free text than a rigid street/area grammar. This module
extracts everything with its own syntax: Makani numbers, PO boxes, postcodes, unit/floor
details, house-number candidates, and landmark relations ("near", "opposite", "بجانب").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .normalize import STREET_TYPES, has_arabic, to_ascii_digits, tokenize

_DELIMS = re.compile(r"[,،;\n|/\\]+(?=\s|$)|[,،;\n|]+")

# --------------------------------------------------------------------------- vocabulary

UNIT_WORDS = {
    "apt", "apartment", "flat", "floor", "fl", "level", "office", "ofc", "shop", "room", "unit",
    "suite", "store", "شقه", "شقة", "الطابق", "طابق", "مكتب", "محل", "غرفه", "غرفة", "وحده",
    "وحدة", "دور",
}  # fmt: skip

BUILDING_WORDS = {
    "villa", "building", "bldg", "bld", "house", "plot", "tower", "no", "number", "num", "nr",
    "فيلا", "مبني", "مبنى", "بنايه", "بناية", "عمارة", "عماره", "منزل", "بيت", "رقم", "قطعه",
    "قطعة", "برج",
}  # fmt: skip

_TYPE_VOCAB = ["street", "avenue", "boulevard", "corniche", "highway", "roundabout", "interchange"]


def _canonical_type(tok: str) -> str:
    """Repair typos in street-type words: "stredt", "strreet", "sareet" -> "street"."""
    if tok in STREET_TYPES or len(tok) < 5 or not tok.isalpha() or has_arabic(tok):
        return tok
    m = process.extractOne(tok, _TYPE_VOCAB, scorer=fuzz.ratio, score_cutoff=80)
    return m[0] if m else tok


POBOX_RE = re.compile(
    r"(?:p\.?\s?o\.?\s?box|po\s?box|pob|post\s?box|ص\.?\s?ب\.?|صندوق\s+بريد)\s*[:#]?\s*(\d{1,7})",
    re.I,
)
POSTCODE_WORDS = {"postcode", "zip", "postal", "pc", "الرمز", "بريدي"}

# phrase (tokens) -> relation kind
RELATIONS: dict[tuple[str, ...], str] = {
    ("near",): "near", ("nearby",): "near", ("close", "to"): "near", ("around",): "near",
    ("next", "to"): "next_to", ("beside",): "next_to", ("adjacent", "to"): "next_to",
    ("opposite",): "opposite", ("opp",): "opposite", ("across", "from"): "opposite",
    ("facing",): "opposite", ("behind",): "behind", ("in", "front", "of"): "in_front",
    ("after",): "after", ("before",): "before", ("by",): "near", ("at",): "at",
    ("بجانب",): "next_to", ("بجوار",): "next_to", ("جنب",): "next_to", ("بقرب",): "near",
    ("قرب",): "near", ("بالقرب", "من"): "near", ("مقابل",): "opposite", ("قبالة",): "opposite",
    ("قبال",): "opposite", ("خلف",): "behind", ("وراء",): "behind", ("امام",): "in_front",
    ("عند",): "at", ("بعد",): "after", ("قبل",): "before",
}  # fmt: skip

# typical positional uncertainty (metres) around the landmark for each relation
RELATION_RADIUS_M = {
    "at": 40, "next_to": 70, "opposite": 90, "in_front": 80, "behind": 100, "near": 250,
    "after": 400, "before": 400,
}  # fmt: skip

_MAKANI_RE = re.compile(r"(?<!\d)(\d{5})[\s\-]?(\d{5})(?!\d)")


@dataclass
class NumberRef:
    value: str
    pos: int  # token index in `tokens`
    keyword: str | None = None  # building/villa/... that introduced it
    adjacent_type: bool = False  # directly after a street-type word ("Street 23", "شارع 23")
    before_type: bool = False  # directly before one ("29 شارع ..."): usually a house number
    leading: bool = False  # first token of its segment
    segment: int = 0


@dataclass
class ParsedQuery:
    raw: str
    tokens: list[str]
    seg_of: list[int]  # segment index per token
    consumed: list[bool]  # token consumed by a non-name component
    makani: str | None = None
    po_box: str | None = None
    postcode_hint: str | None = None
    unit: str | None = None
    numbers: list[NumberRef] = field(default_factory=list)
    relation: str | None = None
    landmark_span: tuple[int, int] | None = None  # [start, end) token indices
    notes: list[str] = field(default_factory=list)

    @property
    def landmark_tokens(self) -> list[str]:
        if not self.landmark_span:
            return []
        a, b = self.landmark_span
        return self.tokens[a:b]

    def body_indices(self) -> list[int]:
        """Token indices that may belong to a place name."""
        return [i for i, c in enumerate(self.consumed) if not c]


def _find_relation(tokens: list[str], seg_of: list[int]):
    """First relation phrase in the query. Returns (kind, start, phrase_len) or None."""
    n = len(tokens)
    best = None
    for i in range(n):
        for plen in (3, 2, 1):
            if i + plen > n:
                continue
            phrase = tuple(tokens[i : i + plen])
            kind = RELATIONS.get(phrase)
            if kind and len({seg_of[j] for j in range(i, i + plen)}) == 1:
                # a bare "at"/"by"/"after" is too ambiguous inside a street name unless a
                # landmark follows in the same segment
                if i + plen < n and seg_of[i + plen] == seg_of[i]:
                    best = (kind, i, plen)
                    return best
                if i + plen < n and kind in {"near", "next_to", "opposite", "behind", "in_front"}:
                    return (kind, i, plen)
    return best


def parse(raw: str) -> ParsedQuery:
    text = to_ascii_digits(raw)
    notes: list[str] = []

    # --- Makani: 10 digits, optionally written "12345 67890". Remove before tokenizing.
    makani = None
    m = _MAKANI_RE.search(text)
    if m:
        makani = m.group(1) + m.group(2)
        text = text[: m.start()] + " " + text[m.end() :]

    # --- PO box: not a physical location; recorded and removed
    po_box = None
    pm = POBOX_RE.search(text)
    if pm:
        po_box = pm.group(1)
        text = text[: pm.start()] + " " + text[pm.end() :]
        notes.append("po_box")

    # --- split into segments, tokenize
    segs = [s for s in _DELIMS.split(text) if s and s.strip()]
    tokens: list[str] = []
    seg_of: list[int] = []
    for si, seg in enumerate(segs):
        for t in tokenize(seg):
            tokens.append(_canonical_type(t))
            seg_of.append(si)

    consumed = [False] * len(tokens)
    pq = ParsedQuery(raw=raw, tokens=tokens, seg_of=seg_of, consumed=consumed, makani=makani,
                     po_box=po_box, notes=notes)  # fmt: skip

    # --- landmark relation: everything after the phrase to the end of its segment
    rel = _find_relation(tokens, seg_of)
    if rel:
        kind, start, plen = rel
        seg = seg_of[start]
        end = start + plen
        while end < len(tokens) and seg_of[end] == seg:
            end += 1
        if end > start + plen:
            pq.relation = kind
            pq.landmark_span = (start + plen, end)
            for j in range(start, end):
                consumed[j] = True

    # --- unit words (+ following number)
    for i, t in enumerate(tokens):
        if consumed[i]:
            continue
        if t in UNIT_WORDS:
            consumed[i] = True
            if i + 1 < len(tokens) and re.fullmatch(r"\d+[a-z]?", tokens[i + 1]):
                pq.unit = (pq.unit + " " if pq.unit else "") + f"{t} {tokens[i + 1]}"
                consumed[i + 1] = True
            elif i > 0 and re.fullmatch(r"\d+", tokens[i - 1]) and not consumed[i - 1]:
                # "3rd floor" style
                pq.unit = (pq.unit + " " if pq.unit else "") + f"{t} {tokens[i - 1]}"
                consumed[i - 1] = True

    # --- postcode hint (explicit keyword)
    for i, t in enumerate(tokens):
        if t in POSTCODE_WORDS:
            consumed[i] = True
            for j in (i + 1, i + 2):
                if j < len(tokens) and re.fullmatch(r"\d{4,6}", tokens[j]) and not consumed[j]:
                    pq.postcode_hint = tokens[j]
                    consumed[j] = True
                    break

    # --- numbers: classify
    seg_start = {}
    for i, s in enumerate(seg_of):
        seg_start.setdefault(s, i)
    for i, t in enumerate(tokens):
        if consumed[i] or not re.fullmatch(r"\d+[a-z]?(?:[/.\-]\d+)?", t):
            continue
        kw = None
        if i > 0 and tokens[i - 1] in BUILDING_WORDS and seg_of[i - 1] == seg_of[i]:
            kw = tokens[i - 1]
        elif i + 1 < len(tokens) and tokens[i + 1] in BUILDING_WORDS and seg_of[i + 1] == seg_of[i]:
            kw = tokens[i + 1]
        adj = i > 0 and tokens[i - 1] in STREET_TYPES and seg_of[i - 1] == seg_of[i]
        bef = i + 1 < len(tokens) and tokens[i + 1] in STREET_TYPES and seg_of[i + 1] == seg_of[i]
        pq.numbers.append(
            NumberRef(
                value=t,
                pos=i,
                keyword=kw,
                adjacent_type=adj,
                before_type=bef,
                leading=(seg_start.get(seg_of[i]) == i),
                segment=seg_of[i],
            )  # fmt: skip
        )
    # building keywords themselves are not name tokens
    for nr in pq.numbers:
        if nr.keyword:
            for j in (nr.pos - 1, nr.pos + 1):
                if 0 <= j < len(tokens) and tokens[j] == nr.keyword:
                    consumed[j] = True
    for i, t in enumerate(tokens):
        if t in BUILDING_WORDS and not consumed[i]:
            consumed[i] = True
    return pq
