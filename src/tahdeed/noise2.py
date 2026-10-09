"""Independent query generator v2: Latin text produced from the *Arabic* names.

``noise.py`` (v1) perturbs the English OSM names. People mostly do the opposite: they know the
Arabic name and write it in Latin letters by ear. v2 simulates that with three romanisation styles
and shares no tables with v1 or with the matcher's consonant classes:

* ``formal``   - careful romanisation (kh, sh, th, dh, gh, q, j), definite article assimilation
* ``gulf``     - Gulf pronunciation: q->g, j->y or j, k->ch in some words, th->t/s, dh->z/d
* ``arabizi``  - chat-style digits (3 = ع, 7 = ح, 5 = خ, 2 = ء, 9 = ص/ق, 6 = ط, 8 = غ)

Short vowels are not written in Arabic, so they are inserted at random: the matcher must not depend
on them.
"""

from __future__ import annotations

import random

from .gazetteer import Gazetteer
from .noise import Query, split_of
from .normalize import has_arabic

STYLES = ("formal", "gulf", "arabizi")

# letter -> options per style (first = most common)
_MAP: dict[str, dict[str, list[str]]] = {
    "ب": {"*": ["b"]},
    "ت": {"*": ["t"], "arabizi": ["t"]},
    "ث": {"formal": ["th"], "gulf": ["th", "s", "t"], "arabizi": ["th", "s"]},
    "ج": {"formal": ["j"], "gulf": ["j", "y", "j"], "arabizi": ["j", "g"]},
    "ح": {"formal": ["h"], "gulf": ["h"], "arabizi": ["7", "h"]},
    "خ": {"formal": ["kh"], "gulf": ["kh", "k"], "arabizi": ["5", "kh", "7'"]},
    "د": {"*": ["d"]},
    "ذ": {"formal": ["dh"], "gulf": ["z", "dh", "d"], "arabizi": ["th", "z", "d"]},
    "ر": {"*": ["r"]},
    "ز": {"*": ["z"]},
    "س": {"*": ["s"]},
    "ش": {"formal": ["sh"], "gulf": ["sh"], "arabizi": ["sh", "ch"]},
    "ص": {"formal": ["s"], "gulf": ["s"], "arabizi": ["9", "s"]},
    "ض": {"formal": ["d"], "gulf": ["d", "z"], "arabizi": ["9'", "d"]},
    "ط": {"formal": ["t"], "gulf": ["t"], "arabizi": ["6", "t"]},
    "ظ": {"formal": ["z"], "gulf": ["z", "dh"], "arabizi": ["6'", "z", "th"]},
    "ع": {"formal": ["", "'"], "gulf": ["", "'"], "arabizi": ["3", "a"]},
    "غ": {"formal": ["gh"], "gulf": ["gh", "g"], "arabizi": ["8", "gh", "3'"]},
    "ف": {"*": ["f"]},
    "ق": {"formal": ["q"], "gulf": ["g", "q", "g"], "arabizi": ["9", "q", "g"]},
    "ك": {"formal": ["k"], "gulf": ["k", "ch", "k"], "arabizi": ["k"]},
    "ل": {"*": ["l"]},
    "م": {"*": ["m"]},
    "ن": {"*": ["n"]},
    "ه": {"*": ["h", ""]},
    "ء": {"formal": ["'", ""], "gulf": [""], "arabizi": ["2", ""]},
    "أ": {"*": ["a", ""]},
    "إ": {"*": ["i", "e", ""]},
    "آ": {"*": ["aa", "a"]},
    "ؤ": {"*": ["o", "u", "w"]},
    "ئ": {"*": ["e", "y", "i"]},
    "گ": {"*": ["g"]},
    "چ": {"*": ["ch"]},
    "پ": {"*": ["p", "b"]},
    "ڤ": {"*": ["v", "f"]},
}
_LONG = {
    "ا": ["a", "aa", "a"],
    "و": ["u", "oo", "ou", "o", "w"],
    "ي": ["i", "ee", "y", "ie"],
    "ى": ["a", "y", "i"],
}
_SUN = set("تثدذرزسشصضطظلن")
_VOW = ["a", "a", "a", "e", "i", "u", "o"]


def _pick(rng: random.Random, opts: list[str]) -> str:
    return opts[0] if rng.random() < 0.55 else rng.choice(opts)


def translit_word(w: str, rng: random.Random, style: str) -> str:
    """Romanise one Arabic word (no diacritics expected) in the given style."""
    w = "".join(ch for ch in w if not ("ً" <= ch <= "ٟ" or ch == "ـ"))
    out: list[str] = []
    prev_cons = False
    for i, ch in enumerate(w):
        if ch in _LONG:
            opts = _LONG[ch]
            if ch == "و" and i == 0:
                opts = ["w", "u", "wa"]
            if ch == "ي" and i == 0:
                opts = ["y", "i"]
            if ch == "ا" and i == 0:
                opts = ["a", "", "e"]
            out.append(_pick(rng, opts))
            prev_cons = False
            continue
        if ch == "ة":
            out.append(rng.choice(["a", "ah", "a", "eh", "h", "ia" if prev_cons else "a"]))
            prev_cons = False
            continue
        table = _MAP.get(ch)
        if table is None:
            out.append(ch if ch.isalnum() else "")
            continue
        opts = table.get(style) or table.get("*") or table.get("formal") or [""]
        s = _pick(rng, opts)
        if prev_cons and s and rng.random() < 0.75:  # short vowel between consonants
            out.append(rng.choice(_VOW))
        out.append(s)
        prev_cons = bool(s) and s[-1].isalpha()
    return "".join(out)


def translit_phrase(text: str, rng: random.Random, style: str) -> str:
    words = text.split()
    out: list[str] = []
    for w in words:
        if not has_arabic(w):
            out.append(w)
            continue
        if w.startswith("ال") and len(w) > 3:
            base = w[2:]
            art = "al" if rng.random() < 0.85 else "el"
            if style == "formal" and base[0] in _SUN and rng.random() < 0.5:
                first = translit_word(base[0], rng, style)
                art = "a" + (first if first else "l")  # as-/ar-/ash- assimilation
            out.append(art)
            out.append(translit_word(base, rng, style))
        elif w.startswith("ال"):
            out.append(translit_word(w, rng, style))
        else:
            out.append(translit_word(w, rng, style))
    s = " ".join(x for x in out if x)
    return s.title() if rng.random() < 0.6 else s


_TYPE_EN = {"street": ["Street", "St", "Road", "Rd", "Street"]}


def make_address_queries_v2(
    g: Gazetteer, n: int, split: str, seed: int = 0, hole_rate: float = 0.0
) -> list[Query]:
    rng = random.Random(f"v2-{seed}-{split}")
    ids = [
        i
        for i, a in enumerate(g.addr)
        if a[15] and a[1] and a[2] and has_arabic(a[2])
        and split_of(f"{a[8]}|{a[5] or a[4] or ''}") == split
    ]  # fmt: skip
    rng.shuffle(ids)
    out: list[Query] = []
    for i in ids[:n]:
        a = g.addr[i]
        style = rng.choices(STYLES, weights=[0.35, 0.4, 0.25])[0]
        tags = ["v2", f"style_{style}"]
        street = translit_phrase(a[2].replace("شارع", "").strip() or a[2], rng, style)
        stype = rng.choice(["Street", "St", "Road", "", "Street"]) if "شارع" in a[2] else ""
        street_txt = f"{street} {stype}".strip()
        district = translit_phrase(a[4], rng, style) if a[4] and rng.random() < 0.65 else None
        city = (a[10] if rng.random() < 0.7 else None) if a[10] else None
        slice_name = "full"
        hn = a[1] if rng.random() > 0.08 else None
        if hn is None:
            slice_name = "no_hn"
        elif district is None or city is None:
            slice_name = "partial"
        pieces = [" ".join(x for x in (hn, street_txt) if x)]
        if district:
            pieces.append(district)
        if city:
            pieces.append(city)
        text = (", " if rng.random() < 0.6 else " ").join(pieces)
        if rng.random() < 0.25:
            text = text.lower()
        hidden = rng.random() < hole_rate
        if hidden:
            tags.append("hidden_truth")
        out.append(Query(text, "addr", i, a[12], a[13], tags, slice_name, split, "v2", hidden))
    return out
