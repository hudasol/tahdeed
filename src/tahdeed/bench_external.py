"""Two evaluation sets whose text and truth do not come from OpenStreetMap.

    tahdeed bench fetch-external [--which all|overture|wikidata] [--out bench/data_external]

* ``overture_places``: UAE places from Overture Maps Places (public S3 parquet, anonymous read).
  Query = place name + the free-text address string written by the business or its data provider.
  Truth = the source's place coordinate. Source licences (CDLA-Permissive-2.0, Apache-2.0, CC0-1.0)
  are recorded per row.
* ``wikidata_addresses``: UAE items with coordinates (P625) and a street address statement (P6375)
  or a street (P669) with optional house number (P670), from query.wikidata.org (CC0).

Both are human or business written text. They are NOT synthetic and they are NOT driver-direction
text. Truth is the source's coordinate and can be wrong. The files live in their own directory with
their own licence notice and are never mixed into the ODbL files of ``bench/data``.

Rows use the same fields as ``bench/data/*.jsonl`` so ``tahdeed bench score`` works unchanged.
Everything is deterministic given the pinned Overture release, the seed and (for Wikidata) the
retrieval date recorded in the manifest. Nothing here was used to tune Tahdeed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from .geo import haversine_m, nearest_city
from .normalize import normalize_text
from .privacy import redact_pii

USER_AGENT = "tahdeed-bench/1.0 (+https://github.com/hudasol/tahdeed)"
ROOT = Path(__file__).resolve().parents[2]
EXT_DATA = ROOT / "bench" / "data_external"
OVERTURE_RELEASE = "2026-10-21.0"  # pinned: the newest release when this set was built
OVERTURE_SEED = 20261028
MIN_CONFIDENCE = 0.7
UAE_BOX = (51.0, 22.4, 56.6, 26.2)  # lon W, lat S, lon E, lat N
MAX_FROM_CITY_CENTRE_M = 150_000
NAME_CAP = 3  # at most this many rows with the same normalised name (chains)
OVERTURE_TARGETS = {"dubai": 1000, "abu dhabi": 1000, "sharjah": 500, "other": 500}
SPARQL_URL = "https://query.wikidata.org/sparql"

# ----------------------------------------------------------------------------- privacy guard

# Public venue categories only (Overture `taxonomy.primary`). Anything else is dropped, which also
# removes home businesses, freelancers and individual agents.
_VENUE_EXACT = {
    "cafe", "coffee_shop", "bakery", "bar", "lounge", "dessert_shop", "ice_cream_shop", "gym",
    "hotel", "lodging", "resort", "hospital", "outpatient_care_facility", "dental_clinic",
    "pharmacy", "shopping_mall", "shopping", "grocery_store", "convenience_store",
    "warehouse_club_store", "school", "private_school", "preschool", "college_university",
    "education", "government_office", "bank", "bank_or_credit_union", "atm",
    "muslim_place_of_worship", "place_of_worship", "church_cathedral", "park", "beach",
    "historic_site", "gas_station", "airport", "museum", "library", "cinema", "stadium",
    "post_office", "police_department", "fire_department", "community_services_non_profits",
    "amusement_park", "zoo", "aquarium", "marina", "metro_station", "train_station",
    "bus_station", "landmark_and_historical_building", "tourist_attraction", "shopping_center",
    "hypermarket", "supermarket", "department_store", "embassy", "courthouse",
}  # fmt: skip
_VENUE_SUFFIX = ("_restaurant", "_museum", "_hotel", "_school", "_university", "_hospital")
_TITLE = re.compile(
    r"^(?:dr|mr|mrs|ms|eng|prof|sheikh|shaikh|sheikha|haji|hajji|capt)\b\.?|"
    r"^(?:د\.|دكتور|الدكتور|المهندس|الشيخ|الشيخة|السيد)(?:\s|$)",
    re.I,
)
_RESIDENCE = re.compile(
    r"\b(?:villa|flat|apt|apartment|room|house\s*(?:no|#|number)?\s*\d+|h\.?\s?no)\b|"
    r"(?:فيلا|شقة|منزل)",
    re.I,
)
_BUSINESS_WORDS = re.compile(
    r"\b(?:restaurant|cafe|caf[eé]|coffee|hotel|resort|mall|center|centre|hospital|clinic|medical|"
    r"school|academy|nursery|university|college|institute|bank|pharmacy|market|supermarket|"
    r"hypermarket|store|shop|mosque|masjid|park|beach|station|airport|museum|gallery|club|gym|"
    r"fitness|spa|salon|bakery|sweets|trading|company|llc|l\.l\.c|est|group|tower|towers|building|"
    r"plaza|court|fort|palace|library|police|department|authority|ministry|municipality|"
    r"embassy|consulate|court|office|services|centre|garden|zoo|stadium|marina|souq|souk)\b|"
    r"(?:مطعم|مقهى|فندق|مجمع|مركز|مستشفى|عيادة|مدرسة|جامعة|كلية|بنك|مصرف|صيدلية|سوق|"
    r"مسجد|جامع|حديقة|شاطئ|محطة|مطار|متحف|نادي|مخبز|شركة|مؤسسة|برج|مول|هيئة|وزارة|بلدية|"
    r"قصر|حصن|مكتبة|شرطة|دائرة|مكتب|خدمات|روضة|معهد|أكاديمية|مركز)",
    re.I,
)
_PERSONAL_NAME = re.compile(
    r"^[A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,2}$"
)  # "Aisha Khan", "John A. Smith"
_ARABIC_PERSON = re.compile(r"^(?:[ء-ي]+\s+){1,3}(?:بن|ابن|آل|ال)\s+[ء-ي]+$")


def is_public_venue(category: str | None) -> bool:
    if not category:
        return False
    return category in _VENUE_EXACT or category.endswith(_VENUE_SUFFIX)


def looks_private(name: str, address: str) -> bool:
    """Conservative: True when the record could be a private person or residence.

    A false positive costs one row out of tens of thousands; a false negative could publish a
    person's name next to a home address, so any doubt drops the row."""
    n = name.strip()
    if _TITLE.search(n) or _RESIDENCE.search(address) or _RESIDENCE.search(n):
        return True
    if not _BUSINESS_WORDS.search(n):
        if _PERSONAL_NAME.match(n) or _ARABIC_PERSON.match(n):
            return True
    return False


_WEB = re.compile(r"https?:|www\.|\.(?:com|ae|net|org)\b|goo\.gl|maps\.app|@", re.I)


def _clean(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace("\\n", ", ").replace("\n", ", ")
    s = re.sub(r"[\x00-\x1f\x7f​-‏‪-‮]", " ", s)
    s = s.replace('"', " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip(" ,;")


def _lang_of(text: str) -> str:
    ar = sum("؀" <= c <= "ۿ" for c in text)
    lat = sum(c.isascii() and c.isalpha() for c in text)
    if ar and lat:
        return "mixed"
    return "ar" if ar else "en"


def stratum_of(lat: float, lon: float) -> str:
    key = nearest_city(lat, lon).key
    return key if key in ("dubai", "abu dhabi", "sharjah") else "other"


def _in_uae(lat: float, lon: float) -> bool:
    c = nearest_city(lat, lon)
    return (
        UAE_BOX[0] <= lon <= UAE_BOX[2]
        and UAE_BOX[1] <= lat <= UAE_BOX[3]
        and haversine_m(lat, lon, c.lat, c.lon) <= MAX_FROM_CITY_CENTRE_M
    )


# ----------------------------------------------------------------------------- Overture


def clean_overture_record(rec: dict) -> dict | None:
    """One raw Overture row -> a candidate benchmark row, or None when it must not be published.

    ``rec`` keys: id, name, address, category, confidence, operating_status, lat, lon, sources
    (list of {dataset, license}). Phones and emails are never read."""
    if rec.get("operating_status") not in (None, "open"):
        return None
    if (rec.get("confidence") or 0) < MIN_CONFIDENCE or not is_public_venue(rec.get("category")):
        return None
    name, addr = _clean(rec.get("name")), _clean(rec.get("address"))
    if not (2 <= len(name) <= 80 and 12 <= len(addr) <= 200):
        return None
    lat, lon = rec.get("lat"), rec.get("lon")
    if lat is None or lon is None or not _in_uae(lat, lon):
        return None
    for part in (name, addr):  # contact details or web links anywhere in the text: drop the row
        if redact_pii(part)[1] or _WEB.search(part):
            return None
    if looks_private(name, addr):
        return None
    text = addr if normalize_text(name) in normalize_text(addr) else f"{name}, {addr}"
    srcs = rec.get("sources") or []
    datasets = sorted({s.get("dataset") for s in srcs if s.get("dataset")})
    licences = sorted({s.get("license") for s in srcs if s.get("license")})
    if not licences:
        return None  # no recorded licence, no publication
    city = nearest_city(lat, lon).key
    return {
        "text": text, "lang": _lang_of(text), "kind": "poi",
        "lat": round(float(lat), 7), "lon": round(float(lon), 7),
        "truth_city": city, "truth_city_geo": city, "truth_ref": f"overture/{rec['id']}",
        "hole": False, "stratum": stratum_of(lat, lon), "evidence": None, "noise": [],
        "synthetic": False, "text_kind": "business_written", "category": rec["category"],
        "source_datasets": datasets, "source_licenses": licences,
        "source_confidence": round(float(rec["confidence"]), 3),
        "_name_key": normalize_text(name),
    }  # fmt: skip


def sample_overture(
    records: Iterable[dict],
    targets: dict[str, int] = OVERTURE_TARGETS,
    seed: int = OVERTURE_SEED,
) -> list[dict]:
    """Deterministic stratified sample of cleaned rows (ids assigned in stratum order)."""
    pools: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for rec in sorted(records, key=lambda r: r["id"]):
        row = clean_overture_record(rec)
        if row is None:
            continue
        key = (row["_name_key"], normalize_text(row["text"]))
        if key in seen:
            continue
        seen.add(key)
        pools[row["stratum"]].append(row)
    out: list[dict] = []
    for stratum, n in targets.items():
        pool = pools.get(stratum, [])
        random.Random(f"{seed}:{stratum}").shuffle(pool)
        names: Counter = Counter()
        taken = 0
        for row in pool:
            if taken >= n:
                break
            if names[row["_name_key"]] >= NAME_CAP:
                continue
            names[row["_name_key"]] += 1
            out.append(row)
            taken += 1
    rows = []
    for i, row in enumerate(out):
        row = {k: v for k, v in row.items() if not k.startswith("_")}
        rows.append({"id": f"overture_places-{i:05d}", "set": "overture_places",
                     "split": "external", **row})  # fmt: skip
    return rows


OVERTURE_SQL = """
SELECT id, names.primary AS name, addresses[1].freeform AS address, addresses[1].country AS country,
       confidence, taxonomy.primary AS category, operating_status,
       (bbox.ymin + bbox.ymax) / 2 AS lat, (bbox.xmin + bbox.xmax) / 2 AS lon,
       to_json(sources) AS sources
FROM read_parquet('s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*',
                  hive_partitioning=1)
WHERE bbox.xmin >= {w} AND bbox.xmax <= {e} AND bbox.ymin >= {s} AND bbox.ymax <= {n}
  AND addresses[1].country = 'AE' AND addresses[1].freeform IS NOT NULL
  AND confidence >= {conf}
"""  # fmt: skip


def query_overture(release: str = OVERTURE_RELEASE) -> list[dict]:
    """Anonymous read of the public bucket with HTTP range requests (no key). Needs duckdb."""
    import duckdb

    for k in [k for k in os.environ if k.startswith("AWS_") and k != "AWS_CA_BUNDLE"]:
        del os.environ[
            k
        ]  # injected placeholder credentials would turn an anonymous read into a 403
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    w, s, e, n = UAE_BOX
    cur = con.execute(OVERTURE_SQL.format(release=release, w=w, s=s, e=e, n=n, conf=MIN_CONFIDENCE))
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r, strict=True))
        d["sources"] = json.loads(d["sources"]) if d["sources"] else []
        out.append(d)
    return out


# ----------------------------------------------------------------------------- Wikidata

SPARQL = """
SELECT ?item ?label ?c ?addr ?street ?streetLabel ?hn WHERE {
  ?item wdt:P17 wd:Q878; wdt:P625 ?c.
  FILTER NOT EXISTS { ?item wdt:P31 wd:Q5 }
  OPTIONAL { ?item wdt:P6375 ?addr }
  OPTIONAL { ?item wdt:P669 ?street . ?street rdfs:label ?streetLabel . FILTER(LANG(?streetLabel) IN ("en", "ar")) }
  OPTIONAL { ?item wdt:P670 ?hn }
  FILTER(BOUND(?addr) || BOUND(?street))
  ?item rdfs:label ?label . FILTER(LANG(?label) IN ("en", "ar"))
}
"""  # fmt: skip
_POINT = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")


def _val(b: dict, k: str) -> tuple[str, str] | None:
    x = b.get(k)
    return (x["value"], x.get("xml:lang", "")) if x else None


def parse_wikidata(bindings: list[dict]) -> list[dict]:
    """SPARQL bindings -> benchmark rows (sorted by Q number, ids assigned in that order)."""
    items: dict[str, dict] = {}
    for b in bindings:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        it = items.setdefault(
            qid, {"labels": {}, "addr": {}, "street": {}, "hn": set(), "coords": set()}
        )
        m = _POINT.match(b["c"]["value"]) if "c" in b else None
        if m:
            it["coords"].add((round(float(m.group(2)), 6), round(float(m.group(1)), 6)))
        lab = _val(b, "label")
        if lab:
            it["labels"][lab[1]] = lab[0]
        ad = _val(b, "addr")
        if ad:
            it["addr"][ad[1] or "en"] = ad[0]
        st = _val(b, "streetLabel")
        if st:
            it["street"][st[1]] = st[0]
        hn = _val(b, "hn")
        if hn:
            it["hn"].add(hn[0])
    rows = []
    for qid in sorted(items, key=lambda q: int(q[1:]) if q[1:].isdigit() else 10**12):
        it = items[qid]
        coords = sorted(it["coords"])
        if not coords or not it["labels"]:
            continue
        lat, lon = coords[0]
        if any(haversine_m(lat, lon, la, lo) > 200 for la, lo in coords):
            continue  # ambiguous truth
        if not _in_uae(lat, lon):
            continue
        if it["addr"]:
            source, stmt = "P6375", it["addr"]
        elif it["street"] and len(it["hn"]) <= 1:
            source, stmt = "P669", it["street"]
        else:
            continue
        lang = next((k for k in ("en", "ar") if k in stmt), min(stmt))
        label = it["labels"].get(lang) or next(iter(it["labels"].values()))
        label = _clean(label)
        street_text = _clean(stmt[lang])
        if source == "P669":
            number = next(iter(it["hn"]), "")
            street_text = f"{number} {street_text}".strip()
        if re.fullmatch(r"Q\d+", label) or len(street_text) < 4:
            continue
        if redact_pii(label)[1] or redact_pii(street_text)[1]:
            continue
        text = (
            street_text
            if normalize_text(label) in normalize_text(street_text)
            else f"{label}, {street_text}"
        )
        city = nearest_city(lat, lon).key
        rows.append({
            "id": "", "set": "wikidata_addresses", "split": "external", "text": text,
            "lang": _lang_of(text), "kind": "poi", "lat": lat, "lon": lon, "truth_city": city,
            "truth_city_geo": city, "truth_ref": f"wikidata/{qid}", "hole": False,
            "stratum": "address_statement" if source == "P6375" else "street_statement",
            "evidence": None, "noise": [], "synthetic": False, "text_kind": "human_written",
            "wikidata_property": source, "source_licenses": ["CC0-1.0"],
        })  # fmt: skip
    for i, r in enumerate(rows):
        r["id"] = f"wikidata_addresses-{i:05d}"
    return rows


def sparql_request(query: str, retries: int = 6, wait_cap: float = 1800.0) -> list[dict]:
    """One query with an identifying User-Agent. Honours 429 Retry-After (capped), otherwise slows
    down; never retries faster than once per second."""
    url = SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
                return json.load(resp)["results"]["bindings"]
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 500, 502, 503, 504):
                raise
            ra = ex.headers.get("Retry-After", "")
            pause = min(wait_cap, float(ra) + 5 if ra.isdigit() else 30.0 * 2**attempt)
            print(
                f"wikidata: HTTP {ex.code}, waiting {pause:.0f}s (attempt {attempt + 1})",
                flush=True,
            )
            time.sleep(max(pause, 1.0))
    raise RuntimeError("wikidata: still rate limited after retries; try again later")


# ----------------------------------------------------------------------------- writing


def _write_set(out: Path, name: str, rows: list[dict]) -> str:
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{name}.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _update_manifest(out: Path, name: str, entry: dict) -> None:
    mp = out / "MANIFEST.json"
    man: dict = (
        json.loads(mp.read_text(encoding="utf-8"))
        if mp.exists()
        else {"version": "1.0.0", "kind": "external text, not OpenStreetMap", "sets": {}}
    )
    man["sets"][name] = entry
    mp.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_overture(out: Path, release: str = OVERTURE_RELEASE) -> dict:
    rows = sample_overture(query_overture(release))
    sha = _write_set(out, "overture_places", rows)
    lic = Counter(x for r in rows for x in r["source_licenses"])
    entry = {
        "n": len(rows), "generator": "overture_places", "split": "external",
        "seed": OVERTURE_SEED, "release": release, "min_confidence": MIN_CONFIDENCE,
        "targets": OVERTURE_TARGETS,
        "strata": dict(Counter(r["stratum"] for r in rows)),
        "licenses_seen_per_row": dict(lic),
        "contamination": "never seen by developers",
        "description": "business written name + free-text address; truth = source coordinate",
        "sha256": sha,
    }  # fmt: skip
    _update_manifest(out, "overture_places", entry)
    print(f"overture_places: {len(rows)} rows {entry['strata']}")
    return entry


def fetch_wikidata(out: Path) -> dict:
    bindings = sparql_request(SPARQL)
    rows = parse_wikidata(bindings)
    sha = _write_set(out, "wikidata_addresses", rows)
    entry = {
        "n": len(rows), "generator": "wikidata_sparql", "split": "external", "seed": None,
        "retrieved": time.strftime("%Y-%m-%d", time.gmtime()), "raw_bindings": len(bindings),
        "strata": dict(Counter(r["stratum"] for r in rows)),
        "contamination": "never seen by developers",
        "description": "human edited address statements (P6375, P669/P670); truth = P625",
        "sha256": sha,
    }  # fmt: skip
    _update_manifest(out, "wikidata_addresses", entry)
    print(f"wikidata_addresses: {len(rows)} rows {entry['strata']}")
    return entry


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("fetch-external", help="build the OSM-independent evaluation sets")
    p.add_argument("--which", choices=["all", "overture", "wikidata"], default="all")
    p.add_argument("--out", default=str(EXT_DATA))
    p.add_argument("--release", default=OVERTURE_RELEASE, help="Overture release to read")


def run(a: argparse.Namespace) -> int:
    out = Path(a.out)
    if a.which in ("all", "overture"):
        fetch_overture(out, a.release)
    if a.which in ("all", "wikidata"):
        fetch_wikidata(out)
    return 0
