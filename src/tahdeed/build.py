"""Build the gazetteer (SQLite) from an OpenStreetMap PBF extract.

Requires ``pyosmium`` (``pip install tahdeed[build]``). The output database is derived
from OSM and therefore ODbL-licensed; it is not committed to the repository.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from .geo import CITIES, City, haversine_m, nearest_city
from .normalize import skeleton

SCHEMA = """
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE addresses (
  id INTEGER PRIMARY KEY, hn TEXT, street_ar TEXT, street_en TEXT,
  district_ar TEXT, district_en TEXT, sub_ar TEXT, sub_en TEXT,
  city_key TEXT, city_ar TEXT, city_en TEXT, postcode TEXT,
  lat REAL, lon REAL, osm TEXT, structured INTEGER
);
CREATE TABLE streets (
  id INTEGER PRIMARY KEY, name TEXT, name_ar TEXT, name_en TEXT, stype TEXT,
  city_key TEXT, lat REAL, lon REAL, minlat REAL, minlon REAL, maxlat REAL, maxlon REAL,
  length_m REAL, osm TEXT
);
CREATE TABLE areas (
  id INTEGER PRIMARY KEY, name_ar TEXT, name_en TEXT, kind TEXT, city_key TEXT,
  lat REAL, lon REAL, radius_m REAL, n INTEGER, source TEXT
);
CREATE TABLE pois (
  id INTEGER PRIMARY KEY, name TEXT, name_ar TEXT, name_en TEXT, kind TEXT,
  street TEXT, city_key TEXT, hn TEXT, lat REAL, lon REAL, osm TEXT
);
"""

ROAD_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified",
    "living_street", "pedestrian", "road", "service", "motorway_link", "trunk_link",
    "primary_link", "secondary_link", "tertiary_link",
}  # fmt: skip
PLACE_AREA_KINDS = {
    "suburb", "neighbourhood", "quarter", "town", "village", "hamlet", "city", "island",
    "locality", "square", "district", "borough", "city_block",
}  # fmt: skip
POI_KEYS = (
    "amenity", "shop", "tourism", "leisure", "office", "healthcare", "railway", "aeroway",
    "public_transport", "building", "man_made", "historic", "craft", "emergency", "landuse",
)  # fmt: skip
_HN_OK = re.compile(r"^\d{1,5}[a-z]?(?:[/\-]\d{1,4})?$", re.I)

_CITY_ALIASES: dict[str, str] = {}
for _c in CITIES:
    for _n in (_c.en, _c.ar, _c.key, *_c.aliases):
        _CITY_ALIASES[skeleton(_n) or _n.lower()] = _c.key
_CITY_ALIASES[skeleton("Al Dhafra Region")] = "madinat zayed"
_CITY_ALIASES[skeleton("منطقة الظفرة")] = "madinat zayed"


def city_key_from_text(text: str | None) -> str | None:
    """Map a free-text city ("Dubai Media City, Dubai", "أبوظبي") to a city key."""
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"[,،]", text) if p.strip()]
    for p in reversed(parts):
        k = _CITY_ALIASES.get(skeleton(p))
        if k:
            return k
    return _CITY_ALIASES.get(skeleton(text))


def _hn_ok(hn: str | None) -> bool:
    return bool(hn and _HN_OK.match(hn.strip()))


def _first(*vals: str | None) -> str | None:
    for v in vals:
        if v and v.strip():
            return v.strip()
    return None


def _split_names(tags) -> tuple[str | None, str | None, str | None]:
    """Return (display name, arabic name, english name) for an OSM element's tags."""
    from .normalize import has_arabic

    name = tags.get("name")
    ar = tags.get("name:ar")
    en = tags.get("name:en") or tags.get("int_name")
    if name and not ar and has_arabic(name):
        ar = name
    if name and not en and not has_arabic(name):
        en = name
    return name, ar, en


def build(pbf: str | Path, out: str | Path, *, verbose: bool = True) -> dict[str, int]:
    """Parse ``pbf`` and write a gazetteer SQLite database to ``out``."""
    import osmium  # imported lazily: build-time dependency only

    t0 = time.time()
    addrs: list[tuple] = []
    streets: list[tuple] = []
    places: list[tuple] = []
    pois: list[tuple] = []

    def addr_row(tags, lat, lon, osm_id):
        hn = tags.get("addr:housenumber")
        street = _first(tags.get("addr:street"), tags.get("addr:street:en"))
        if not (_hn_ok(hn) and street):
            return None
        city_txt = _first(tags.get("addr:city:en"), tags.get("addr:city"), tags.get("addr:city:ar"))
        ck = city_key_from_text(city_txt) or city_key_from_text(tags.get("addr:city"))
        if ck is None:
            ck = nearest_city(lat, lon).key
        city = next(c for c in CITIES if c.key == ck)
        structured = int(bool(tags.get("addr:district") or tags.get("addr:subdistrict")))
        return (
            hn.strip(),
            tags.get("addr:street"),
            tags.get("addr:street:en"),
            tags.get("addr:district"),
            tags.get("addr:district:en"),
            tags.get("addr:subdistrict"),
            tags.get("addr:subdistrict:en"),
            ck,
            city.ar,
            city.en,
            tags.get("addr:postcode"),
            lat,
            lon,
            osm_id,
            structured,
        )

    def poi_row(tags, lat, lon, osm_id):
        name, ar, en = _split_names(tags)
        if not name:
            return None
        kind = next((f"{k}={tags[k]}" for k in POI_KEYS if k in tags and tags[k] != "yes"), None)
        if kind is None:
            kind = next((k for k in POI_KEYS if k in tags), None)
        if kind is None:
            return None
        hn = tags.get("addr:housenumber")
        city_txt = _first(tags.get("addr:city:en"), tags.get("addr:city"))
        ck = city_key_from_text(city_txt) or nearest_city(lat, lon).key
        return (
            name,
            ar,
            en,
            kind,
            _first(tags.get("addr:street"), tags.get("addr:street:en")),
            ck,
            hn if _hn_ok(hn) else None,
            lat,
            lon,
            osm_id,
        )

    def place_row(tags, lat, lon):
        kind = tags.get("place")
        name, ar, en = _split_names(tags)
        if not name or kind not in PLACE_AREA_KINDS:
            return None
        ck = nearest_city(lat, lon).key
        return (ar, en or (name if not ar else None), kind, ck, lat, lon, 0.0, 0, "osm-place")

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if not n.tags or not n.location.valid():
                return
            tags = n.tags
            lat, lon = n.location.lat, n.location.lon
            osm = f"n{n.id}"
            if "place" in tags:
                r = place_row(tags, lat, lon)
                if r:
                    places.append(r)
            if "addr:housenumber" in tags and "name" not in tags:
                r = addr_row(tags, lat, lon, osm)
                if r:
                    addrs.append(r)
            elif "addr:housenumber" in tags and "addr:district" in tags:
                r = addr_row(tags, lat, lon, osm)
                if r:
                    addrs.append(r)
            if "name" in tags:
                r = poi_row(tags, lat, lon, osm)
                if r:
                    pois.append(r)

        def way(self, w):
            tags = w.tags
            if not tags:
                return
            hw = tags.get("highway")
            is_street = hw in ROAD_TYPES and "name" in tags
            has_addr = "addr:housenumber" in tags
            is_place = "place" in tags and "name" in tags
            is_poi = "name" in tags and any(k in tags for k in POI_KEYS)
            if not (is_street or has_addr or is_place or is_poi):
                return
            lats, lons = [], []
            for nd in w.nodes:
                if nd.location.valid():
                    lats.append(nd.location.lat)
                    lons.append(nd.location.lon)
            if not lats:
                return
            lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
            osm = f"w{w.id}"
            if is_street:
                name, ar, en = _split_names(tags)
                length = 0.0
                for i in range(1, len(lats)):
                    length += haversine_m(lats[i - 1], lons[i - 1], lats[i], lons[i])
                ck = nearest_city(lat, lon).key
                streets.append(
                    (
                        name,
                        ar,
                        en,
                        hw,
                        ck,
                        lat,
                        lon,
                        min(lats),
                        min(lons),
                        max(lats),
                        max(lons),
                        length,
                        osm,
                    )  # fmt: skip
                )
            if has_addr and not is_street:
                r = addr_row(tags, lat, lon, osm)
                if r:
                    addrs.append(r)
            if is_place:
                r = place_row(tags, lat, lon)
                if r:
                    places.append(r)
            if is_poi and not is_street:
                r = poi_row(tags, lat, lon, osm)
                if r:
                    pois.append(r)

    Handler().apply_file(str(pbf), locations=True, idx="flex_mem")
    if verbose:
        print(
            f"parsed in {time.time() - t0:.0f}s: {len(addrs)} addresses, {len(streets)} street "
            f"segments, {len(places)} place features, {len(pois)} POIs"
        )

    areas = _derive_areas(addrs, places)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO addresses(hn,street_ar,street_en,district_ar,district_en,sub_ar,sub_en,"
        "city_key,city_ar,city_en,postcode,lat,lon,osm,structured) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        addrs,
    )
    con.executemany(
        "INSERT INTO streets(name,name_ar,name_en,stype,city_key,lat,lon,minlat,minlon,maxlat,"
        "maxlon,length_m,osm) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        streets,
    )
    con.executemany(
        "INSERT INTO areas(name_ar,name_en,kind,city_key,lat,lon,radius_m,n,source) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        areas,
    )
    con.executemany(
        "INSERT INTO pois(name,name_ar,name_en,kind,street,city_key,hn,lat,lon,osm) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        pois,
    )
    for k, v in {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(Path(pbf).name),
        "license": "ODbL 1.0 (c) OpenStreetMap contributors",
    }.items():
        con.execute("INSERT INTO meta VALUES (?,?)", (k, v))
    con.execute("CREATE INDEX ix_addr_city ON addresses(city_key)")
    con.commit()
    con.close()
    counts = {
        "addresses": len(addrs),
        "streets": len(streets),
        "areas": len(areas),
        "pois": len(pois),
    }
    if verbose:
        print("wrote", out, counts, f"in {time.time() - t0:.0f}s")
    return counts


def _derive_areas(addrs: list[tuple], places: list[tuple]) -> list[tuple]:
    """Areas = OSM place features + districts/subdistricts aggregated from address points."""
    groups: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for a in addrs:
        d_ar, d_en, s_ar, s_en, ck, lat, lon = a[3], a[4], a[5], a[6], a[7], a[11], a[12]
        if d_ar or d_en:
            groups[("district", d_ar, d_en, ck)].append((lat, lon))
            if s_ar or s_en:
                groups[("subdistrict", s_ar, s_en, ck, d_en or d_ar)].append((lat, lon))
    rows: list[tuple] = list(places)
    for key, pts in groups.items():
        kind, ar, en, ck = key[0], key[1], key[2], key[3]
        if kind == "subdistrict":
            # keep the parent district in the English name for disambiguation of codes like "W9"
            en = f"{en} ({key[4]})" if en and key[4] else en
        la = sum(p[0] for p in pts) / len(pts)
        lo = sum(p[1] for p in pts) / len(pts)
        ds = sorted(haversine_m(la, lo, p[0], p[1]) for p in pts)
        radius = ds[int(0.9 * (len(ds) - 1))] if ds else 0.0
        rows.append((ar, en, kind, ck, la, lo, radius, len(pts), "derived-from-addresses"))
    return rows


def city_by_key(key: str) -> City:
    return next(c for c in CITIES if c.key == key)


__all__ = ["build", "city_key_from_text", "math"]
