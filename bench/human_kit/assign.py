"""Deterministic assignment of 5 public places per volunteer.

Given an ordered list of volunteer codes, every volunteer gets 5 places from the level-A/B
places in ``places.csv``. Assignment is a pure function of (places, ordered codes, seed): the
same inputs always give the same sheets. Selection is greedy and balanced:

1. coverage: a place may only be chosen while its coverage is within ``slack`` of the least
   covered place (slack starts at 0 and grows only when a sheet would otherwise be too uniform),
   so every place ends up with roughly equal coverage;
2. variety inside a sheet: among those, prefer categories and emirates not yet in the sheet;
3. ties are broken by SHA-256(seed | code | place_id), i.e. "seeded by the volunteer code".

Adding a code in the middle of the list changes later sheets: append new codes at the end of
``codes.txt`` and never reorder it once volunteers have received their sheets.

Outputs (per volunteer, in ``--out``): ``<code>.json`` (name and category only, never
coordinates), and with ``--form`` a personalised offline copy ``form_<code>.html`` whose embedded
assignment contains only that volunteer's 5 places, plus ``assignment_key.csv`` for the organiser.

    python bench/human_kit/assign.py --n 30 --out sheets/            # random codes -> codes.txt
    python bench/human_kit/assign.py --codes codes.txt --out sheets/ --form bench/human_kit/form/index.html
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import secrets
import string
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PER_VOLUNTEER = 5
LEVEL_RANK = {"A": 0, "B": 1, "C": 2}
_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1L")


def load_places(path: Path | str, min_level: str = "B") -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if LEVEL_RANK.get(r["verified_level"], 9) <= LEVEL_RANK[min_level]]


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16)


def _build_sheet(code, places, cover, per, seed, slack):
    chosen: list[dict] = []
    cats: Counter = Counter()
    ems: Counter = Counter()
    for _ in range(per):
        left = [p for p in places if p not in chosen]
        floor = min(cover[p["place_id"]] for p in left)
        elig = [p for p in left if cover[p["place_id"]] <= floor + slack]
        best = min(
            elig,
            key=lambda p: (
                cats[p["category"]],
                ems[p["emirate"]],
                cover[p["place_id"]],
                _h(seed, code, p["place_id"]),
            ),
        )
        chosen.append(best)
        cats[best["category"]] += 1
        ems[best["emirate"]] += 1
    return chosen, len(cats), len(ems)


def assign(
    codes: list[str],
    places: list[dict],
    *,
    per: int = PER_VOLUNTEER,
    seed: str = "tahdeed-human-kit-1",
    max_slack: int = 3,
    min_categories: int = 4,
    min_emirates: int = 3,
) -> dict[str, list[dict]]:
    """Return ``{code: [place rows]}`` (order inside a sheet is a seeded shuffle).

    Each sheet is built with the tightest coverage slack (0, 1, ...) that still gives at least
    ``min_categories`` categories and ``min_emirates`` emirates; otherwise the most varied
    attempt is kept.
    """
    if len(places) < per:
        raise ValueError(f"need at least {per} places, got {len(places)}")
    if len(set(codes)) != len(codes):
        raise ValueError("volunteer codes must be unique")
    cover: Counter = Counter({p["place_id"]: 0 for p in places})
    out: dict[str, list[dict]] = {}
    for code in codes:
        best_try = None
        for slack in range(max_slack + 1):
            chosen, nc, ne = _build_sheet(code, places, cover, per, seed, slack)
            score = (min(nc, min_categories), min(ne, min_emirates))
            if best_try is None or score > best_try[0]:
                best_try = (score, chosen)
            if score == (min_categories, min_emirates):
                break
        chosen = best_try[1]
        for p in chosen:
            cover[p["place_id"]] += 1
        chosen.sort(key=lambda p: _h(seed, "order", code, p["place_id"]))
        out[code] = chosen
    return out


def coverage_report(assignment: dict[str, list[dict]], places: list[dict]) -> dict:
    c = Counter(p["place_id"] for sheet in assignment.values() for p in sheet)
    counts = [c.get(p["place_id"], 0) for p in places]
    return {
        "volunteers": len(assignment),
        "descriptions": sum(counts),
        "min_cover": min(counts),
        "max_cover": max(counts),
        "uncovered": [p["place_id"] for p in places if c.get(p["place_id"], 0) == 0],
        "by_category": dict(Counter(p["category"] for s in assignment.values() for p in s)),
        "by_emirate": dict(Counter(p["emirate"] for s in assignment.values() for p in s)),
    }


def sheet_json(code: str, sheet: list[dict]) -> dict:
    """What the volunteer sees: name and category only (no coordinates, no address)."""
    return {
        "volunteer_code": code,
        "places": [
            {
                "place_id": p["place_id"],
                "name_en": p["name_en"],
                "name_ar": p["name_ar"],
                "category": p["category"],
            }
            for p in sheet
        ],
    }


def make_codes(n: int, prefix: str = "V") -> list[str]:
    seen: set[str] = set()
    while len(seen) < n:
        seen.add(prefix + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(6)))
    return sorted(seen)


def embed_in_form(template: str, sheet: dict) -> str:
    marker = '<script id="assignments" type="application/json">'
    i = template.index(marker) + len(marker)
    j = template.index("</script>", i)
    payload = json.dumps({sheet["volunteer_code"]: sheet}, ensure_ascii=False).replace("</", "<\\/")
    return template[:i] + payload + template[j:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--places", default=str(HERE / "places.csv"))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--codes", help="text file, one volunteer code per line (order matters)")
    g.add_argument(
        "--n", type=int, help="generate N random codes and write them to <out>/codes.txt"
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="tahdeed-human-kit-1")
    ap.add_argument("--min-level", default="B", choices=["A", "B"])
    ap.add_argument("--form", help="form/index.html template: also write form_<code>.html")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.n:
        codes = make_codes(a.n)
        (out / "codes.txt").write_text("\n".join(codes) + "\n", encoding="utf-8")
    else:
        codes = [
            c.strip() for c in Path(a.codes).read_text(encoding="utf-8").splitlines() if c.strip()
        ]
    places = load_places(a.places, a.min_level)
    asg = assign(codes, places, seed=a.seed)
    template = Path(a.form).read_text(encoding="utf-8") if a.form else None
    with open(out / "assignment_key.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["volunteer_code", "slot", "place_id", "name_en", "category", "emirate"])
        for code, sheet in asg.items():
            sj = sheet_json(code, sheet)
            (out / f"{code}.json").write_text(
                json.dumps(sj, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if template:
                (out / f"form_{code}.html").write_text(
                    embed_in_form(template, sj), encoding="utf-8"
                )
            for k, p in enumerate(sheet, 1):
                w.writerow([code, k, p["place_id"], p["name_en"], p["category"], p["emirate"]])
    print(json.dumps(coverage_report(asg, places), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
