"""Rebuild ``places.csv`` and ``places_sources.md`` from public sources.

Primary coordinates: the local OpenStreetMap-derived gazetteer (read-only, ``pois`` table,
(c) OpenStreetMap contributors, ODbL 1.0).  Secondary coordinates: Wikidata property P625
(CC0), fetched live from the Wikidata SPARQL endpoint.  Nothing here uses a commercial
geocoder, and no coordinate is typed in by hand: every number in ``places.csv`` is read from
one of those two sources and the distance between them is computed with a haversine.

Verification levels
    A  OSM and Wikidata agree within 50 m AND the Wikidata P625 statement carries a reference
       to a Wikimedia project (i.e. it was entered by a Wikipedia editor, not copied from OSM).
    B  one usable source, or two sources that disagree by more than 50 m (primary = OSM, the
       disagreement is stated in ``notes``), or two sources that agree but where the Wikidata
       statement has no reference, so independence cannot be demonstrated.
    C  never written (dropped).

Usage (needs network for Wikidata)::

    PYTHONPATH=src python bench/human_kit/build_places.py \
        --gazetteer data/gazetteer.sqlite --out bench/human_kit
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

from tahdeed.geo import haversine_m

ACCESS_DATE = "2026-10-11"
UA = "tahdeed-benchmark-kit/0.1 (open research benchmark; contact via project repo)"
MAX_DISAGREE_M = 1500.0  # beyond this the two records are probably not the same feature: drop

# (category, emirate, osm element id in the gazetteer, wikidata Q-id or "", English name, Arabic name or "")
# Arabic is taken from OSM/Wikidata when left empty.
SPEC: list[tuple[str, str, str, str, str, str]] = [
    # --- malls (single, well-known sites) ---
    ("mall", "Dubai", "w225672808", "Q2386719", "BurJuman Mall", ""),
    ("mall", "Dubai", "w175115425", "Q1066448", "Mall of the Emirates", ""),
    ("mall", "Dubai", "w102832548", "Q511504", "Ibn Battuta Mall", ""),
    ("mall", "Dubai", "w105359350", "Q6873078", "Mirdif City Centre", ""),
    ("mall", "Dubai", "w25780630", "Q4037155", "Deira City Centre", ""),
    ("mall", "Abu Dhabi", "w150781737", "Q4670143", "Abu Dhabi Mall", ""),
    ("mall", "Abu Dhabi", "w91673883", "Q6941289", "Mushrif Mall", ""),
    ("mall", "Abu Dhabi", "w91662999", "Q6399626", "Khalidiyah Mall", ""),
    ("mall", "Al Ain", "w115331651", "Q4703453", "Mall of Al Ain", ""),
    ("mall", "Sharjah", "w146379257", "", "Sahara Centre", "مركز صحارى"),
    ("mall", "Sharjah", "w416311679", "", "Sharjah City Centre", ""),
    ("mall", "Ajman", "w179619234", "Q55607691", "City Centre Ajman", ""),
    ("mall", "Fujairah", "w211573873", "Q17003358", "City Centre Fujairah", ""),
    # --- hospitals ---
    ("hospital", "Dubai", "w244376544", "Q25461650", "American Hospital Dubai", ""),
    ("hospital", "Dubai", "w230629140", "Q20707857", "Iranian Hospital Dubai", ""),
    ("hospital", "Dubai", "w98642909", "Q5310555", "Dubai Hospital", ""),
    ("hospital", "Abu Dhabi", "w154471715", "Q30254311", "Corniche Hospital", ""),
    ("hospital", "Abu Dhabi", "n4128424723", "Q5214934", "Danat Al Emarat Hospital", ""),
    ("hospital", "Al Ain", "w282551279", "Q30281077", "Tawam Hospital", "مستشفى توام"),
    ("hospital", "Al Ain", "w481666350", "Q30254307", "Al Ain Hospital", "مستشفى العين"),
    ("hospital", "Sharjah", "w210276596", "", "Al Qassimi Hospital", ""),
    ("hospital", "Ajman", "w195869554", "Q4699898", "Ajman Specialty General Hospital", ""),
    ("hospital", "Ras Al Khaimah", "n3830464334", "Q18392892", "RAK Hospital", ""),
    ("hospital", "Fujairah", "w542394152", "", "Fujairah Hospital", ""),
    # --- Dubai Metro stations ---
    ("metro", "Dubai", "n6588569794", "Q107132419", "Al Rigga Metro Station", ""),
    ("metro", "Dubai", "n6588516080", "Q106858396", "Ibn Battuta Metro Station", ""),
    ("metro", "Dubai", "n6588569798", "Q107132454", "World Trade Centre Metro Station", ""),
    ("metro", "Dubai", "n6588569785", "Q106848102", "Dubai Internet City Metro Station", ""),
    ("metro", "Dubai", "n2017967833", "Q106848604", "Airport Terminal 3 Metro Station", ""),
    ("metro", "Dubai", "n6584833640", "Q16335316", "Creek Metro Station", ""),
    ("metro", "Dubai", "n6584833624", "Q16335322", "Salah Al Din Metro Station", ""),
    ("metro", "Dubai", "n6584833629", "Q21160974", "Al Ghubaiba Metro Station", ""),
    ("metro", "Dubai", "n604304348", "Q4998884", "Burj Khalifa/Dubai Mall Metro Station", ""),
    ("metro", "Dubai", "n6584833637", "Q30006736", "Al Jaddaf Metro Station", ""),
    # --- universities ---
    ("university", "Sharjah", "w205717627", "Q4115992", "American University of Sharjah", ""),
    ("university", "Sharjah", "w376417463", "Q7896294", "University of Sharjah", ""),
    ("university", "Abu Dhabi", "w238976174", "Q566189", "New York University Abu Dhabi", ""),
    ("university", "Abu Dhabi", "w1078799256", "Q6399651", "Khalifa University", ""),
    ("university", "Abu Dhabi", "w1252862959", "Q4670157", "Abu Dhabi University", ""),
    ("university", "Dubai", "w991864074", "Q467144", "American University in Dubai", ""),
    ("university", "Dubai", "w224330161", "Q4835741", "BITS Pilani Dubai Campus", ""),
    ("university", "Dubai", "w892875450", "Q5738583", "Heriot-Watt University Dubai", ""),
    ("university", "Al Ain", "w443938035", "Q1544739", "United Arab Emirates University", ""),
    ("university", "Ajman", "w238918057", "Q15210735", "City University Ajman", ""),
    (
        "university",
        "Ras Al Khaimah",
        "w146768713",
        "Q7294680",
        "RAK Medical and Health Sciences University",
        "",
    ),
    # --- public buildings (museums, libraries, municipal, transit hubs) ---
    ("public_building", "Dubai", "w1054289435", "Q22948398", "Museum of the Future", ""),
    ("public_building", "Dubai", "w386649647", "Q20386392", "Dubai Frame", ""),
    ("public_building", "Dubai", "w723549616", "Q55623557", "Mohammed bin Rashid Library", ""),
    ("public_building", "Abu Dhabi", "w498046180", "Q3176133", "Louvre Abu Dhabi", ""),
    ("public_building", "Abu Dhabi", "n4001910834", "", "Qasr Al Hosn", "قصر الحصن"),
    (
        "public_building",
        "Sharjah",
        "w502129798",
        "Q7489771",
        "Sharjah Museum of Islamic Civilization",
        "",
    ),
    (
        "public_building",
        "Sharjah",
        "n4758530527",
        "Q130542448",
        "Al Jubail Bus Station Sharjah",
        "",
    ),
    ("public_building", "Ajman", "w239711162", "Q12238661", "Ajman Museum", ""),
    ("public_building", "Al Ain", "w256644089", "Q1052105", "Al Ain National Museum", ""),
    ("public_building", "Al Ain", "w1123701063", "Q3272665", "Al Ain Palace Museum", ""),
    ("public_building", "Fujairah", "w195209154", "Q5953247", "Fujairah Fort", ""),
    # --- parks ---
    ("park", "Dubai", "w242815345", "Q23583803", "Zabeel Park", ""),
    ("park", "Dubai", "w495449950", "Q2522355", "Safa Park", ""),
    ("park", "Abu Dhabi", "n3957148058", "", "Khalifa Park", "حديقة خليفة"),
    ("park", "Ras Al Khaimah", "w932819267", "", "Al Jazeera Park", "حديقة الجزيرة"),
]

_AR = re.compile(r"[؀-ۿ]")
_COMMERCIAL = re.compile(r"google|apple|mapbox|here\.com|bing|tomtom", re.I)
_WIKIMEDIA = re.compile(r"Wikipedia|Wikivoyage|Wikimedia|Wikisource", re.I)


def fetch_wikidata(qids: list[str]) -> dict[str, dict]:
    vals = " ".join("wd:" + q for q in qids)
    q = f"""SELECT ?i ?la ?c ?srcl ?stated ?url WHERE {{ VALUES ?i {{ {vals} }}
      ?i p:P625 ?st. ?st ps:P625 ?c.
      OPTIONAL{{?i rdfs:label ?la FILTER(lang(?la)='ar')}}
      OPTIONAL{{?st prov:wasDerivedFrom ?ref.
        OPTIONAL{{?ref pr:P143 ?src. ?src rdfs:label ?srcl FILTER(lang(?srcl)='en')}}
        OPTIONAL{{?ref pr:P248 ?stated0. ?stated0 rdfs:label ?stated FILTER(lang(?stated)='en')}}
        OPTIONAL{{?ref pr:P854 ?url}} }} }}"""
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120
    ) as fh:
        data = json.load(fh)
    out: dict[str, dict] = {}
    for b in data["results"]["bindings"]:
        qid = b["i"]["value"].rsplit("/", 1)[-1]
        lon, lat = (
            float(x) for x in b["c"]["value"].replace("Point(", "").replace(")", "").split()
        )
        g = lambda k, b=b: b.get(k, {}).get("value", "")  # noqa: E731
        ref = g("srcl") or g("stated") or g("url")
        cur = out.get(qid)
        # keep a referenced statement over an unreferenced one
        if cur is None or (ref and not cur["ref"]):
            out[qid] = {"lat": lat, "lon": lon, "ar": g("la"), "ref": ref}
    return out


def clean_ar(s: str) -> str:
    return re.sub(r"\s*\((مترو دبي)\)", "", s).strip()


def build(gazetteer: Path, out_dir: Path) -> None:
    con = sqlite3.connect(f"file:{gazetteer}?mode=ro", uri=True)
    wd = fetch_wikidata(sorted({s[3] for s in SPEC if s[3]}))
    rows, src_lines, dropped = [], [], []
    for cat, emirate, osm, qid, en, ar_override in SPEC:
        r = con.execute("select name,name_en,lat,lon,kind from pois where osm=?", (osm,)).fetchone()
        if r is None:
            dropped.append((en, "OSM element not in gazetteer"))
            continue
        name_osm, name_en_osm, lat, lon, kind = r
        w = wd.get(qid) if qid else None
        notes: list[str] = []
        if w and _COMMERCIAL.search(w["ref"]):
            notes.append(
                f"Wikidata coordinate is referenced to a commercial map ({w['ref']}); not used"
            )
            w = None
        d = None
        sec = ""
        wd_ar = w["ar"] if w else ""
        if w:
            d = haversine_m(lat, lon, w["lat"], w["lon"])
            if d > MAX_DISAGREE_M:
                notes.append(
                    f"Wikidata point {d:.0f} m away ignored (imprecise or different feature)"
                )
                w, d = None, None
        if w:
            sec = f"Wikidata {qid} P625" + (f" (ref: {w['ref']})" if w["ref"] else "")
            if d <= 50 and _WIKIMEDIA.search(w["ref"]):
                level = "A"
            else:
                level = "B"
                if d <= 50:
                    notes.append(
                        f"agree within {d:.0f} m but Wikidata P625 is unreferenced/non-Wikimedia ({w['ref'] or 'no reference'}): independence not demonstrable"
                    )
                else:
                    notes.append(
                        f"OSM and Wikidata disagree by {d:.0f} m (OSM used; large site or imprecise Wikidata point)"
                    )
        else:
            level = "B"
            notes.append("single source (OSM)")
        if d is not None and d > 50 and cat in ("mall", "university", "park", "hospital"):
            notes.append(
                "area feature: OSM point is a polygon centroid, entrance may be hundreds of metres away"
            )
        if ar_override:
            notes.append("name_ar supplied by the maintainer (no Arabic name in the sources)")
        ar = ar_override or (name_osm if _AR.search(name_osm or "") else "") or clean_ar(wd_ar)
        if cat == "metro" and ar and not ar.startswith("محطة"):
            ar = "محطة مترو " + ar
        if not ar:
            notes.append("no Arabic name found in sources")
        urls = [f"https://www.openstreetmap.org/{'node' if osm[0] == 'n' else 'way'}/{osm[1:]}"]
        if qid:
            urls.append(f"https://www.wikidata.org/wiki/{qid}")
        pid = f"P{len(rows) + 1:03d}"
        rows.append(
            {
                "place_id": pid,
                "name_en": en,
                "name_ar": ar,
                "category": cat,
                "emirate": emirate,
                "lat": f"{lat:.6f}",
                "lon": f"{lon:.6f}",
                "coord_source_primary": f"OpenStreetMap {osm} ({kind}; gazetteer built from uae.osm.pbf 2026-10-09)",
                "coord_source_secondary": sec,
                "source_urls": " ".join(urls),
                "verified_level": level,
                "notes": "; ".join(notes),
            }
        )
        src_lines.append((pid, en, level, osm, qid, d, w["ref"] if w else "", urls))
    cols = [
        "place_id",
        "name_en",
        "name_ar",
        "category",
        "emirate",
        "lat",
        "lon",
        "coord_source_primary",
        "coord_source_secondary",
        "source_urls",
        "verified_level",
        "notes",
    ]
    with open(out_dir / "places.csv", "w", newline="", encoding="utf-8") as fh:
        w_ = csv.DictWriter(fh, fieldnames=cols)
        w_.writeheader()
        w_.writerows(rows)
    lv = {k: sum(1 for r in rows if r["verified_level"] == k) for k in "AB"}
    md = [
        "# Place sources",
        "",
        "Generated by `build_places.py`. Coordinates are copied from the sources below, never typed in by hand.",
        "",
        "- Primary: OpenStreetMap, via the local read-only gazetteer (built 2026-10-09 from `uae.osm.pbf`), (c) OpenStreetMap contributors, ODbL 1.0.",
        f"- Secondary: Wikidata property P625 (CC0), fetched {ACCESS_DATE} from query.wikidata.org.",
        "- Not used: Google, Apple, Mapbox, HERE or any commercial geocoder. Official-website coordinates were not collected (UAE operator sites rarely publish them), so level A means OSM + Wikidata only.",
        "- Caveat: Wikidata coordinates carrying a Wikipedia reference were entered by human editors, but their upstream map is not recorded, so independence is best-effort, not proven.",
        "- Emirate is assigned by the project from the place's real location, NOT from the gazetteer `city_key` (which mislabels some Dubai and Sharjah features).",
        "",
        f"Counts: A={lv['A']}, B={lv['B']}, total={len(rows)}. Dropped: {len(dropped)}.",
        "",
        "| place_id | name | level | OSM element | Wikidata | OSM-Wikidata distance (m) | Wikidata P625 reference | accessed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pid, en, level, osm, qid, d, ref, urls in src_lines:
        md.append(
            f"| {pid} | {en} | {level} | [{osm}]({urls[0]}) | {('[' + qid + '](' + urls[1] + ')') if qid else '-'} | {'' if d is None else f'{d:.0f}'} | {ref or '-'} | {ACCESS_DATE} |"
        )
    if dropped:
        md += ["", "## Dropped", ""] + [f"- {n}: {why}" for n, why in dropped]
    (out_dir / "places_sources.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} places: {lv}; dropped {len(dropped)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gazetteer", type=Path, default=Path("data/gazetteer.sqlite"))
    ap.add_argument("--out", type=Path, default=Path(__file__).parent)
    a = ap.parse_args()
    build(a.gazetteer, a.out)


if __name__ == "__main__":
    main()
