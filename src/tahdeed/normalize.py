"""Text normalization for UAE addresses.

Two jobs:

1. Canonicalize text within a script (Arabic diacritics/alef/ya variants, Arabic-Indic
   digits, Latin case/accents/apostrophes).
2. Produce a *consonant skeleton* so that an Arabic name and its many Latin spellings
   land on the same (or very close) key: "Jumeirah", "Jumeira" and "جميرا" all map to
   ``jmr``; "Abu Dhabi", "AbuDhabi" and "أبوظبي" all map to ``bzb``.

The skeleton is deliberately lossy. It is used as a *feature and index key*, never as a
final decision.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------- digits

_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})


def to_ascii_digits(s: str) -> str:
    """Convert Arabic-Indic and Persian digits to ASCII digits."""
    return s.translate(_DIGIT_MAP)


# --------------------------------------------------------------------------- Arabic

_AR_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭـ]")  # incl. tatweel
_AR_RANGE = re.compile("[؀-ۿݐ-ݿࢠ-ࣿ]")
_LATIN_RANGE = re.compile("[A-Za-z]")

_AR_UNIFY = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ی": "ي",
        "ک": "ك",
        "ڤ": "ف",
        "پ": "ب",
        "چ": "ج",
        "گ": "ك",
        "ژ": "ز",
        "ۀ": "ه",
        "ہ": "ه",
        "ھ": "ه",
    }
)


def has_arabic(s: str) -> bool:
    return bool(_AR_RANGE.search(s))


def has_latin(s: str) -> bool:
    return bool(_LATIN_RANGE.search(s))


def script_of(s: str) -> str:
    """Return 'ar', 'en' or 'mixed' (digits/punctuation alone count as 'en')."""
    a, e = has_arabic(s), has_latin(s)
    if a and e:
        return "mixed"
    return "ar" if a else "en"


def normalize_arabic(s: str) -> str:
    """Strip diacritics/tatweel and unify letter variants. Keeps ta-marbuta as is."""
    s = unicodedata.normalize("NFKC", s)
    s = _AR_DIACRITICS.sub("", s)
    return s.translate(_AR_UNIFY)


# --------------------------------------------------------------------------- Latin

_APOS = re.compile("[’‘`´ʻʼʿʾ'​‌‍‎‏]")


def normalize_latin(s: str) -> str:
    """Casefold, strip accents and apostrophes, turn hyphens/underscores into spaces."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _APOS.sub("", s)
    s = s.replace("-", " ").replace("_", " ")
    return s.lower()


# --------------------------------------------------------------------------- tokens

_TOKEN_RE = re.compile(r"[^\W_]+(?:[./][^\W_]+)*", re.UNICODE)  # keeps 12/3, 4.5 together


def normalize_text(s: str) -> str:
    """Script-aware canonical form: digits ASCII, Arabic unified, Latin lowercased."""
    s = to_ascii_digits(s)
    s = normalize_arabic(s)
    s = normalize_latin(s)
    return s


def tokenize(s: str) -> list[str]:
    """Normalize and split into tokens. Numbers like 12/3 stay together."""
    s = normalize_text(s)
    return _TOKEN_RE.findall(s)


# --------------------------------------------------------------------------- vocabulary

# Definite articles / assimilated forms. Removed from skeletons when not the last token.
LATIN_ARTICLES = {
    "al", "el", "ar", "as", "ash", "at", "ad", "az", "an", "ath", "adh", "ag", "ac",
    "aj", "ak", "aq", "ap",
}  # fmt: skip

# Street-type words -> canonical type tag. Dropped from name keys; kept as a field.
STREET_TYPES: dict[str, str] = {
    "street": "street", "st": "street", "str": "street", "شارع": "street",
    "road": "road", "rd": "road", "طريق": "road",
    "avenue": "avenue", "ave": "avenue", "av": "avenue", "جاده": "avenue", "جادة": "avenue",
    "boulevard": "boulevard", "blvd": "boulevard", "بوليفارد": "boulevard",
    "corniche": "corniche", "كورنيش": "corniche",
    "highway": "highway", "hwy": "highway", "motorway": "highway",
    "lane": "lane", "ln": "lane", "زقاق": "lane", "ممر": "lane", "درب": "lane",
    "سكه": "lane", "سكة": "lane",
    "square": "square", "sq": "square", "ميدان": "square",
    "bridge": "bridge", "جسر": "bridge",
    "tunnel": "tunnel", "نفق": "tunnel",
    "interchange": "interchange", "دوار": "roundabout", "roundabout": "roundabout",
}  # fmt: skip

STOPWORDS = {"the", "of", "in", "at", "to", "and", "is", "في", "و", "ال"}

# --------------------------------------------------------------------------- skeleton

_AR_SKEL = {
    "ب": "b", "ت": "t", "ط": "t", "ث": "s", "س": "s", "ص": "s", "ج": "j",
    "خ": "X", "د": "d", "ض": "d", "ذ": "z", "ز": "z", "ظ": "z", "ر": "r", "ش": "S",
    "غ": "G", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m", "ن": "n",
}  # fmt: skip
# ا ع ء ة ي و ه are handled in code (vowels/finals).

_LATIN_DIGRAPHS = [
    ("sch", "S"),
    ("sh", "S"),
    ("kh", "X"),
    ("gh", "G"),
    ("th", "s"),
    ("dh", "z"),
    ("ch", "j"),
    ("ph", "f"),
    ("ck", "k"),
    ("ts", "s"),
]
_LATIN_SINGLE = {
    "b": "b", "p": "b", "t": "t", "s": "s", "z": "z", "j": "j", "d": "d", "r": "r",
    "f": "f", "v": "f", "q": "k", "k": "k", "g": "k", "l": "l", "m": "m", "n": "n",
    "h": "h", "x": "ks",
}  # fmt: skip
_VOWELS = set("aeiouy")

_CAPITAL_CLASSES = "SXG"


def _collapse(s: str) -> str:
    """Collapse repeated *letters* ("mm" -> "m"); digits are kept ("3111" stays "3111")."""
    out: list[str] = []
    for ch in s:
        if ch.isdigit() or not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _skeleton_arabic_word(w: str) -> str:
    out: list[str] = []
    n = len(w)
    for i, ch in enumerate(w):
        if ch in _AR_SKEL:
            out.append(_AR_SKEL[ch])
        elif ch == "و":
            if i == 0:
                out.append("w")
        elif ch == "ي":
            if i == 0:
                out.append("y")
        elif ch == "ه":
            if i != n - 1:
                out.append("h")
        elif ch == "ح":
            if i != n - 1:  # final h is dropped in both scripts: "Sayh" == "Sayhi"-ish spellings
                out.append("h")
        elif ch.isdigit():
            out.append(ch)
        # ا ع ء ة and anything else: dropped
    return _collapse("".join(out))


def _skeleton_latin_word(w: str) -> str:
    w = re.sub(r"c(?=[eiy])", "s", w)
    w = re.sub(r"c", "k", w)
    for a, b in _LATIN_DIGRAPHS:
        w = w.replace(a, b)
    out: list[str] = []
    n = len(w)
    for i, ch in enumerate(w):
        if ch in _CAPITAL_CLASSES:
            out.append(ch)
        elif ch in _LATIN_SINGLE:
            if ch == "h" and i == n - 1:
                continue  # final h (ta marbuta): "Jumeirah" == "Jumeira"
            out.append(_LATIN_SINGLE[ch])
        elif ch in ("w", "y"):
            if i == 0:
                out.append(ch)
        elif ch in "aeiou":
            continue
        elif ch.isdigit():
            out.append(ch)
    return _collapse("".join(out))


def _skeleton_word(w: str) -> str:
    if has_arabic(w):
        return _skeleton_arabic_word(w)
    return _skeleton_latin_word(w)


def strip_articles(tokens: list[str]) -> list[str]:
    """Drop leading definite articles (Latin tokens and glued Arabic ال)."""
    out: list[str] = []
    last = len(tokens) - 1
    for i, t in enumerate(tokens):
        if t in LATIN_ARTICLES and i != last:
            continue
        if t == "ال" and i != last:
            continue
        if has_arabic(t) and t.startswith("ال") and len(t) >= 4:
            t = t[2:]
        elif has_arabic(t) and t.startswith("لل") and len(t) >= 4:
            t = "ل" + t[2:]
        out.append(t)
    return out


def name_tokens(s: str) -> list[str]:
    """Tokens of a place/street name with articles, stopwords and street-type words removed."""
    toks = tokenize(s)
    toks = [t for t in toks if t not in STOPWORDS]
    toks = [t for t in toks if t not in STREET_TYPES]
    return strip_articles(toks)


def _idafa_fix(tokens: list[str]) -> list[str]:
    """Latin construct-state ta marbuta: "Thanyat Al Manazil" -> "Thanya Al Manazil"."""
    out = []
    last = len(tokens) - 1
    for i, t in enumerate(tokens):
        if i != last and not has_arabic(t) and len(t) >= 4 and t.endswith("at") and t.isalpha():
            t = t[:-1]
        out.append(t)
    return out


def skeleton_tokens(tokens: list[str]) -> list[str]:
    tokens = _idafa_fix(tokens)
    return [k for k in (_skeleton_word(t) for t in tokens) if k]


def skeleton(s: str) -> str:
    """Joined (space-free) consonant skeleton of a name. Empty string if nothing remains."""
    return "".join(skeleton_tokens(name_tokens(s)))


def street_type_of(s: str) -> str | None:
    for t in tokenize(s):
        if t in STREET_TYPES:
            return STREET_TYPES[t]
    return None


def skeleton_of_tokens(tokens: list[str]) -> str:
    """Skeleton for an arbitrary token span (used for n-gram lookups in queries)."""
    toks = [t for t in tokens if t not in STOPWORDS and t not in STREET_TYPES]
    return "".join(skeleton_tokens(strip_articles(toks)))


@dataclass(frozen=True)
class Normalized:
    raw: str
    text: str
    tokens: tuple[str, ...]
    script: str


def normalize(s: str) -> Normalized:
    text = normalize_text(s)
    return Normalized(raw=s, text=text, tokens=tuple(_TOKEN_RE.findall(text)), script=script_of(s))


# --------------------------------------------------------------------------- coarse keys

_COARSE = str.maketrans(
    {
        "X": "k",
        "G": "k",
        "j": "k",
        "y": "k",
        "q": "k",
        "g": "k",
        "S": "s",
        "z": "s",
        "d": "t",
        "p": "b",
        "v": "f",
    }  # fmt: skip
)


def coarse_key(k: str) -> str:
    """Merge consonant classes that transliterations confuse (j/g/k/kh/gh, s/z/sh, d/t).

    Used only as a *fallback* index: much higher recall, lower precision than the skeleton.
    """
    return _collapse(k.translate(_COARSE))
