"""Human-written benchmark: ingest volunteer response files and evaluate the resolver on them.

Workflow (see ``bench/human_kit/README.md``)::

    python -m tahdeed.human ingest  responses/*.json --out human.jsonl
    python -m tahdeed.human evaluate human.jsonl

No data is ever generated here: ``ingest`` only reads files that volunteers produced with
``bench/human_kit/form/index.html``; ``evaluate`` refuses to print any number when there are
fewer than 20 descriptions ("pending real data").

Scope and limitation
    The resolver is run on the place NAME plus the volunteer's free text (``"<name>, <text>"``).
    A volunteer text says how to *reach* a public place ("near the main gate, opposite the petrol
    station, Al Wahda"); many texts therefore contain no formal address (no street, no building
    number), and the resolver may legitimately abstain or return only an area. The benchmark
    measures that honestly: it is a separate, human-written set and must not be pooled with the
    synthetic or gold sets. The truth point is the verified coordinate of the place in
    ``places.csv``; for large sites (malls, campuses, parks) that is a centroid, so the 50 m rate
    is conservative. A "name only" control (same place name, no description) is reported next to
    every row, so the contribution of the description can be read off directly.

Statistics
    Wilson 95% intervals treat descriptions as independent. They are clustered by volunteer and
    by place, so the intervals are somewhat optimistic; report N descriptions and N volunteers
    with every number.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import secrets
import sys
from collections import Counter
from pathlib import Path

from .geo import haversine_m
from .privacy import redact_pii

SCHEMA_VERSION = "1"
MIN_DESCRIPTIONS = 20
MIN_TEXT_LETTERS = 3
MAX_TEXT_CHARS = 600
KIT_DIR = Path(__file__).resolve().parents[2] / "bench" / "human_kit"
DEFAULT_SCHEMA = KIT_DIR / "form" / "schema.json"
DEFAULT_PLACES = KIT_DIR / "places.csv"
SCRIPTS = ("ar", "en", "arabizi", "mixed")

# ----------------------------------------------------------------------------- schema validation


def load_schema(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_SCHEMA
    if not p.exists():
        raise FileNotFoundError(f"response schema not found: {p} (pass --schema)")
    return json.loads(p.read_text(encoding="utf-8"))


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
}


def validate(instance, schema: dict, path: str = "") -> list[tuple[str, str]]:
    """Validate against the JSON-Schema subset used by ``schema.json``.

    Supports type, const, enum, pattern, minLength, maxLength, minItems, maxItems, required,
    properties, additionalProperties (false), items. Returns ``[(json_pointer, message), ...]``.
    """
    errs: list[tuple[str, str]] = []
    t = schema.get("type")
    if t:
        ok = isinstance(instance, _TYPES[t])
        if t in ("integer", "number") and isinstance(instance, bool):
            ok = False
        if not ok:
            return [(path or "/", f"expected {t}")]
    if "const" in schema and (
        instance != schema["const"] or type(instance) is not type(schema["const"])
    ):
        errs.append((path or "/", f"must be {schema['const']!r}"))
    if "enum" in schema and instance not in schema["enum"]:
        errs.append((path or "/", "not an allowed value"))
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append((path or "/", "does not match pattern"))
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append((path or "/", "too short"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append((path or "/", "too long"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append((path or "/", "too few items"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append((path or "/", "too many items"))
        if "items" in schema:
            for i, it in enumerate(instance):
                errs += validate(it, schema["items"], f"{path}/{i}")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                errs.append((f"{path}/{k}", "required"))
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], f"{path}/{k}")
            elif schema.get("additionalProperties") is False:
                errs.append((f"{path}/{k}", "unexpected property"))
    return errs


# ----------------------------------------------------------------------------- script detection

_AR_LETTER = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
# Arabizi digits stand for Arabic letters: 2=ء 3=ع 5=خ 6=ط 7=ح 8=غ 9=ق. A digit glued to Latin
# letters ("3ala", "sha3bi", "7ay", "mosta4fa") is almost never written in English.
_ARABIZI_DIGIT = re.compile(
    r"(?<![A-Za-z0-9])[2356789](?!(?:st|nd|rd|th)\b)[A-Za-z]{2,}|[A-Za-z]{2,}[2356789](?![0-9])|[A-Za-z][2356789][A-Za-z]"
)
_ARABIZI_WORDS = frozenset(
    "3ala 3and 3end 3ind 3nd bjanb bjaneb jamb janb jenb wara gedam gdam godam odam qudam "
    "yemeen yameen yemin yamin yasar yassar shimal shemal dugri dughri dawwar dowar khalas "
    "ba3d b3d ta7t tahet fo2 foug fouq tul tool shari3 share3 shar3 madkhal mdkhal bawwaba "
    "bawaba mostashfa mustashfa mosta4fa mujamma3 mojamma3 mahatta mat3am matam jamea jam3a "
    "bijanb mn men elly illi lazem laazem mashi emshi imshi tole".split()
)


def detect_script(text: str) -> str:
    """Heuristic: ``ar`` | ``en`` | ``arabizi`` | ``mixed`` (documented, not a language ID model)."""
    t = text.translate(_AR_DIGITS)
    n_ar = len(_AR_LETTER.findall(t))
    n_lat = len(_LATIN_LETTER.findall(t))
    if n_ar and n_lat:
        # a few Latin letters inside Arabic text (e.g. "KFC", "ADNOC") still counts as Arabic
        if n_ar >= 3 * n_lat:
            return "ar"
        if n_lat >= 3 * n_ar and n_ar < 3:
            return "arabizi" if _arabizi_score(t) else "en"
        return "mixed"
    if n_ar:
        return "ar"
    if not n_lat:
        return "en"
    return "arabizi" if _arabizi_score(t) else "en"


def _arabizi_score(t: str) -> bool:
    words = re.findall(r"[A-Za-z0-9']+", t.lower())
    hits = sum(1 for w in words if w in _ARABIZI_WORDS)
    digit_hits = len(_ARABIZI_DIGIT.findall(t))
    return digit_hits >= 1 or hits >= 2


# ----------------------------------------------------------------------------- redaction / flags

_HANDLE = re.compile(r"(?<![\w@])@[\w.]{2,}")
_URL = re.compile(
    r"(?:https?://|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ae|me|co|io|app|ly)(?:/\S*)?\b",
    re.I,
)
# 7+ digits (spaces/dashes allowed between them); an unbroken-or-5+5 10-digit Makani is kept
_LONG_DIGITS = re.compile(r"(?<![\d])(?:\d[\s-]?){6,}\d(?![\d])")
_MAKANI = re.compile(r"^[1-9]\d{4}\s?\d{5}$")
_ADDRESS_EN = re.compile(
    r"\b(?:villa|flat|apt|apartment|my\s+(?:house|home|place|flat|apartment|villa|building)"
    r"|our\s+(?:house|home|villa)|house\s*(?:no|number|#)|bldg\s*(?:no|#)?\s*\d+)\b",
    re.I,
)
_ADDRESS_AR = re.compile(r"(?:فيلا|فلة|بيتي|بيتنا|منزلي|منزلنا|شقتي|شقة|بيت رقم|منزل رقم)")
_ADDRESS_AZ = re.compile(r"\b(?:bayti|baiti|manzili|shaqti|shaqqa|faylla)\b", re.I)


def _sub_long_digits(text: str) -> tuple[str, int]:
    n = 0

    def rep(m: re.Match) -> str:
        nonlocal n
        s = m.group(0)
        if _MAKANI.match(s) and not s.startswith("784"):
            return s
        n += 1
        return " "

    return _LONG_DIGITS.sub(rep, text), n


def clean_text(text: str) -> tuple[str, list[str]]:
    """Apply the project PII guard plus @handle / URL / long-digit redaction.

    Returns (clean_text, flags). Redactions give ``pii_redacted:<kind>`` flags; possible personal
    addresses are only *flagged* (``review:possible_personal_address``), never removed.
    """
    flags: list[str] = []
    t = text.translate(_AR_DIGITS)
    t, kinds = redact_pii(t)
    flags += [f"pii_redacted:{k}" for k in kinds]
    for name, rx in (("handle", _HANDLE), ("url", _URL)):
        t, n = rx.subn(" ", t)
        if n:
            flags.append(f"pii_redacted:{name}")
    t, n = _sub_long_digits(t)
    if n:
        flags.append("pii_redacted:long_digits")
    t = re.sub(r"\s+", " ", t).strip()
    if _ADDRESS_EN.search(t) or _ADDRESS_AR.search(t) or _ADDRESS_AZ.search(t):
        flags.append("review:possible_personal_address")
    return t, flags


# ----------------------------------------------------------------------------- ingest


def _hash_id(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}|{code}".encode()).hexdigest()[:12]


def _query_id(vol: str, place_id: str) -> str:
    return "q" + hashlib.sha256(f"{vol}|{place_id}".encode()).hexdigest()[:10]


def _load_salt(salt_file: Path | str | None) -> tuple[str, bool]:
    """Return (salt, persistent). Without a salt file the salt is random for this run only."""
    env = os.environ.get("TAHDEED_HUMAN_SALT")
    if env:
        return env, True
    if salt_file:
        p = Path(salt_file)
        if p.exists():
            return p.read_text(encoding="utf-8").strip(), True
        s = secrets.token_hex(16)
        p.write_text(s + "\n", encoding="utf-8")
        return s, True
    return secrets.token_hex(16), False


def _read_csv_file(path: Path) -> list[dict]:
    """responses_template.csv layout -> one response document per volunteer_code."""
    docs: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("volunteer_code") or "").strip()
            d = docs.setdefault(
                code,
                {
                    "schema_version": SCHEMA_VERSION,
                    "kit": "tahdeed-human-kit",
                    "volunteer_code": code,
                    "consent": {
                        "agreed": (row.get("consent_agreed") or "").strip().lower()
                        in ("1", "yes", "true"),
                        "version": (row.get("consent_version") or "").strip() or "1",
                    },
                    "demographics": {
                        "emirate_residence": (row.get("emirate_residence") or "").strip(),
                        "years_in_uae": (row.get("years_in_uae") or "").strip(),
                    },
                    "responses": [],
                },
            )
            d["responses"].append(
                {
                    "place_id": (row.get("place_id") or "").strip(),
                    "text": row.get("text") or "",
                    "script_self": (row.get("script_self") or "").strip(),
                }
            )
    return list(docs.values())


def _read_docs(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        return _read_csv_file(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, list) else [doc]


def _known_places(places_csv: Path | str | None) -> set[str] | None:
    p = Path(places_csv) if places_csv else DEFAULT_PLACES
    if not p.exists():
        return None
    with open(p, newline="", encoding="utf-8") as fh:
        return {r["place_id"] for r in csv.DictReader(fh)}


def ingest(
    paths,
    out_jsonl,
    *,
    places_csv: Path | str | None = None,
    schema_path: Path | str | None = None,
    salt_file: Path | str | None = None,
    log=print,
) -> dict:
    """Validate response files and write one JSONL record per description.

    Rules: files failing the schema (or without consent) are rejected whole; individual
    entries that are skipped, empty (< 3 letters), unknown (place not in ``places.csv``) or
    duplicates of an earlier (volunteer, place) pair are dropped and counted. Texts are passed
    through the PII guard; possible personal addresses are kept but flagged for manual review.
    Volunteer codes are replaced by a salted hash.
    """
    schema = load_schema(schema_path)
    known = _known_places(places_csv)
    salt, persistent = _load_salt(salt_file)
    if not persistent:
        log(
            "note: no --salt-file given; volunteer hashes are only consistent within this run. "
            "Use --salt-file (kept OUTSIDE the repo) if you will ingest in several batches."
        )
    stats: Counter = Counter()
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in map(Path, paths):
        try:
            docs = _read_docs(raw)
        except (OSError, ValueError) as ex:
            stats["files_unreadable"] += 1
            log(f"reject {raw.name}: unreadable ({type(ex).__name__})")
            continue
        for doc in docs:
            stats["files_seen"] += 1
            errs = validate(doc, schema)
            top = [e for e in errs if not re.match(r"^/responses/\d+(/|$)", e[0])]
            if top:
                stats["files_rejected"] += 1
                log(f"reject {raw.name}: {top[0][0]} {top[0][1]}")
                continue
            bad = {int(m.group(1)) for p, _ in errs if (m := re.match(r"^/responses/(\d+)", p))}
            vol = _hash_id(salt, doc["volunteer_code"])
            demo = doc.get("demographics") or {}
            for i, r in enumerate(doc["responses"]):
                stats["entries_seen"] += 1
                if i in bad:
                    stats["dropped_invalid_entry"] += 1
                    continue
                if r.get("skipped"):
                    stats["dropped_skipped"] += 1
                    continue
                pid = r["place_id"]
                if known is not None and pid not in known:
                    stats["dropped_unknown_place"] += 1
                    continue
                text, flags = clean_text(r.get("text") or "")
                if (
                    len(_AR_LETTER.findall(text)) + len(_LATIN_LETTER.findall(text))
                    < MIN_TEXT_LETTERS
                ):
                    stats["dropped_incomplete"] += 1
                    continue
                key = (vol, pid)
                if key in seen:
                    stats["dropped_duplicate"] += 1
                    continue
                seen.add(key)
                if r.get("pii_warning_acknowledged"):
                    flags.append("volunteer_acknowledged_warning")
                rec = {
                    "query_id": _query_id(vol, pid),
                    "place_id": pid,
                    "text": text[:MAX_TEXT_CHARS],
                    "script": detect_script(text),
                    "volunteer_bucket": vol,
                    "flags": flags,
                    "emirate_residence": demo.get("emirate_residence") or "",
                    "years_in_uae": demo.get("years_in_uae") or "",
                }
                if r.get("script_self"):
                    rec["script_self"] = r["script_self"]
                records.append(rec)
    # same text reused for several places by one volunteer: keep, but mark for review
    by_vol_text: dict[tuple[str, str], list[dict]] = {}
    for rec in records:
        by_vol_text.setdefault((rec["volunteer_bucket"], rec["text"].lower()), []).append(rec)
    for grp in by_vol_text.values():
        if len(grp) > 1:
            for rec in grp:
                rec["flags"].append("review:same_text_for_several_places")
    out = Path(out_jsonl)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    stats["records_written"] = len(records)
    stats["volunteers"] = len({r["volunteer_bucket"] for r in records})
    stats["records_flagged_for_review"] = sum(
        1 for r in records if any(f.startswith("review:") for f in r["flags"])
    )
    log(f"ingest: {dict(stats)} -> {out}")
    if stats["records_flagged_for_review"]:
        log(
            "Records flagged 'review:*' are excluded from `evaluate` until you open the JSONL, "
            "check them, and delete the line or the flag (or pass --include-flagged)."
        )
    return dict(stats)


# ----------------------------------------------------------------------------- evaluate


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (point, low, high) for a binomial proportion; (nan, nan, nan) when n == 0."""
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_places(places_csv: Path | str | None) -> dict[str, dict]:
    p = Path(places_csv) if places_csv else DEFAULT_PLACES
    with open(p, newline="", encoding="utf-8") as fh:
        return {r["place_id"]: r for r in csv.DictReader(fh)}


def _fmt(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    p, lo, hi = wilson(k, n)
    return f"{100 * p:5.1f}% [{100 * lo:4.1f}, {100 * hi:5.1f}] ({k}/{n})"


def _summarise(rows: list[dict]) -> dict:
    n = len(rows)
    out: dict = {
        "n": n,
        "volunteers": len({r["vol"] for r in rows}),
        "status": dict(Counter(r["status"] for r in rows)),
    }
    for variant in ("text", "name_only"):
        d_key = "d" if variant == "text" else "d0"
        for rad in (50, 200, 1000):
            k = sum(1 for r in rows if r[d_key] is not None and r[d_key] <= rad)
            out[f"{variant}_within_{rad}m"] = {"k": k, "n": n, "wilson95": wilson(k, n)[1:]}
    res = [r for r in rows if r["status"] == "resolved"]
    out["resolved_n"] = len(res)
    for rad in (50, 200):
        k = sum(1 for r in res if r["d"] is not None and r["d"] <= rad)
        out[f"resolved_precision_{rad}m"] = {
            "k": k,
            "n": len(res),
            "wilson95": wilson(k, len(res))[1:],
        }
    return out


def _print_block(title: str, s: dict, w) -> None:
    w(f"\n== {title}: N={s['n']} descriptions, {s['volunteers']} volunteers")
    st = ", ".join(f"{k}={v}" for k, v in sorted(s["status"].items()))
    w(f"  status mix: {st}")
    for rad in (50, 200, 1000):
        a, b = s[f"text_within_{rad}m"], s[f"name_only_within_{rad}m"]
        w(
            f"  within {rad:>4} m  name+text: {_fmt(a['k'], a['n'])}   name only: {_fmt(b['k'], b['n'])}"
        )
    for rad in (50, 200):
        a = s[f"resolved_precision_{rad}m"]
        w(f"  resolved-only precision@{rad:<3} m: {_fmt(a['k'], a['n'])}")
    if s["n"] < 10:
        w("  (fewer than 10 descriptions: interval too wide to interpret)")


def evaluate(
    jsonl,
    places_csv: Path | str | None = None,
    *,
    db: Path | str | None = None,
    model: Path | str | None = None,
    include_flagged: bool = False,
    levels: tuple[str, ...] = ("A", "B"),
    resolver=None,
    out_json: Path | str | None = None,
    min_n: int = MIN_DESCRIPTIONS,
    write=print,
) -> dict | None:
    """Run the resolver on each description and report accuracy against the verified places.

    Returns the summary dict, or ``None`` after printing ``pending real data`` when the file is
    missing or holds fewer than ``min_n`` usable descriptions (no numbers are produced).
    """
    p = Path(jsonl)
    if not p.exists():
        write("pending real data")
        return None
    recs = _read_jsonl(p)
    if len(recs) < min_n:
        write("pending real data")
        return None
    places = _load_places(places_csv)
    n_flag = 0
    use: list[dict] = []
    for r in recs:
        pl = places.get(r["place_id"])
        if pl is None or pl["verified_level"] not in levels:
            continue
        if not include_flagged and any(f.startswith("review:") for f in r.get("flags", [])):
            n_flag += 1
            continue
        use.append(r)
    if len(use) < min_n:
        write("pending real data")
        write(
            f"({len(recs)} descriptions in file, {len(use)} usable after excluding unknown places, "
            f"levels outside {','.join(levels)} and {n_flag} awaiting manual review)"
        )
        return None
    if resolver is None:
        from .service import DEFAULT_DB, DEFAULT_MODEL, load_resolver

        resolver = load_resolver(
            Path(db) if db else DEFAULT_DB, Path(model) if model else DEFAULT_MODEL
        )
        if getattr(resolver, "degraded_reason", None):
            write(
                f"WARNING: resolver in degraded mode ({resolver.degraded_reason}); scores are uncalibrated"
            )
    cache: dict[str, tuple[str, float | None, float | None]] = {}

    def run(q: str):
        if q not in cache:
            res = resolver.resolve(q)
            b = res.best
            cache[q] = (res.status, getattr(b, "lat", None), getattr(b, "lon", None))
        return cache[q]

    rows = []
    for r in use:
        pl = places[r["place_id"]]
        lat, lon = float(pl["lat"]), float(pl["lon"])
        name = (pl["name_ar"] or pl["name_en"]) if r["script"] == "ar" else pl["name_en"]
        st, blat, blon = run(f"{name}, {r['text']}")
        st0, blat0, blon0 = run(name)
        rows.append(
            {
                "vol": r["volunteer_bucket"],
                "script": r["script"],
                "status": st,
                "d": haversine_m(blat, blon, lat, lon) if blat is not None else None,
                "d0": haversine_m(blat0, blon0, lat, lon) if blat0 is not None else None,
            }
        )
    summary: dict = {"overall": _summarise(rows), "by_script": {}}
    summary["excluded_for_review"] = n_flag
    write(
        f"Human-written benchmark: {len(rows)} descriptions used ({n_flag} awaiting review excluded)"
    )
    write(
        "Truth = verified place coordinates; Wilson 95% intervals (descriptions treated as independent)."
    )
    _print_block("ALL", summary["overall"], write)
    for sc in SCRIPTS:
        sub = [r for r in rows if r["script"] == sc]
        if sub:
            summary["by_script"][sc] = _summarise(sub)
            _print_block(f"script={sc}", summary["by_script"][sc], write)
    if out_json:
        Path(out_json).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return summary


# ----------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tahdeed.human", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="validate + clean volunteer response files")
    i.add_argument("paths", nargs="+")
    i.add_argument("--out", required=True)
    i.add_argument("--places", default=None)
    i.add_argument("--schema", default=None)
    i.add_argument("--salt-file", default=None, help="private file holding the hashing salt")
    e = sub.add_parser("evaluate", help="evaluate the resolver on the ingested JSONL")
    e.add_argument("jsonl")
    e.add_argument("--places", default=None)
    e.add_argument("--db", default=None)
    e.add_argument("--model", default=None)
    e.add_argument("--json", default=None, help="also write the summary to this file")
    e.add_argument("--include-flagged", action="store_true")
    e.add_argument("--levels", default="A,B")
    a = ap.parse_args(argv)
    if a.cmd == "ingest":
        ingest(a.paths, a.out, places_csv=a.places, schema_path=a.schema, salt_file=a.salt_file)
        return 0
    evaluate(
        a.jsonl,
        a.places,
        db=a.db,
        model=a.model,
        include_flagged=a.include_flagged,
        levels=tuple(x.strip() for x in a.levels.split(",") if x.strip()),
        out_json=a.json,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
