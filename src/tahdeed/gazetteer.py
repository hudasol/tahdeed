"""In-memory gazetteer loaded from the SQLite database written by :mod:`tahdeed.build`."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .geo import CITIES, CITY_BY_KEY
from .normalize import (
    coarse_key,
    name_tokens,
    normalize_text,
    skeleton,
    skeleton_tokens,
)


def sorted_key(s: str) -> str:
    """Order-insensitive skeleton ("Khalifa City" == "مدينة خليفة")."""
    return "".join(sorted(skeleton_tokens(name_tokens(s))))


def keys_of(*names: str | None) -> set[str]:
    """Index keys for one or more spellings of a name (ordered + order-insensitive)."""
    out: set[str] = set()
    for n in names:
        if not n:
            continue
        for part in re.split(r"[;/]", n):
            part = part.strip()
            if not part:
                continue
            k = skeleton(part)
            if k:
                out.add(k)
                sk = sorted_key(part)
                if sk and sk != k:
                    out.add(sk)
    return out


def _bucket(keys: list[str]) -> dict[tuple[int, str], list[str]]:
    """Index by (length, consonant class of the first letter): typos rarely hit the first letter."""
    out: dict[tuple[int, str], list[str]] = defaultdict(list)
    for k in keys:
        out[(len(k), coarse_key(k)[:1])].append(k)
    return dict(out)


def norm_hn(hn: str | None) -> str:
    if not hn:
        return ""
    s = normalize_text(hn).strip().replace(" ", "")
    m = re.match(r"^0*(\d+)(.*)$", s)
    return (m.group(1) + m.group(2)) if m else s


def hn_int(hn: str) -> int | None:
    m = re.match(r"^(\d+)", hn or "")
    return int(m.group(1)) if m else None


@dataclass
class KeyEntry:
    """Everything the gazetteer knows under one name key."""

    addr: list[int]
    streets: list[int]
    areas: list[int]
    pois: list[int]


class Gazetteer:
    """Columnar, index-backed view of the gazetteer."""

    def __init__(self) -> None:
        self.meta: dict[str, str] = {}
        # addresses
        self.addr: list[tuple] = []
        self.addr_lat = np.zeros(0)
        self.addr_lon = np.zeros(0)
        self.addr_street_keys: list[frozenset[str]] = []
        self.addr_area_keys: list[frozenset[str]] = []
        self.addr_hn: list[str] = []
        self.addr_by_street_hn: dict[tuple[str, str], list[int]] = defaultdict(list)
        self.addr_by_street: dict[str, list[int]] = defaultdict(list)
        self.addr_by_postcode: dict[str, list[int]] = defaultdict(list)
        # streets / areas / pois
        self.streets: list[tuple] = []
        self.street_lat = np.zeros(0)
        self.street_lon = np.zeros(0)
        self.areas: list[tuple] = []
        self.pois: list[tuple] = []
        self.street_by_key: dict[str, list[int]] = defaultdict(list)
        self.area_by_key: dict[str, list[int]] = defaultdict(list)
        self.poi_by_key: dict[str, list[int]] = defaultdict(list)
        self.city_by_key_alias: dict[str, str] = {}
        # coarse-key (consonant-class) fallback indices: coarse -> exact keys
        self.street_coarse: dict[str, list[str]] = defaultdict(list)
        self.area_coarse: dict[str, list[str]] = defaultdict(list)
        self.poi_coarse: dict[str, list[str]] = defaultdict(list)
        # fuzzy candidate lists (keys with at least 4 characters)
        # distinct surface names per key (how lossy is this key?)
        self.street_ambig: dict[str, int] = {}
        self.area_ambig: dict[str, int] = {}
        self.poi_ambig: dict[str, int] = {}
        self.fuzzy_by_len: dict[str, dict[tuple[int, str], list[str]]] = {}
        self.street_key_list: list[str] = []
        self.area_key_list: list[str] = []
        self.poi_key_list: list[str] = []

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: str | Path) -> Gazetteer:
        g = cls()
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        g.meta = dict(con.execute("SELECT k, v FROM meta"))
        g.addr = con.execute(
            "SELECT id, hn, street_ar, street_en, district_ar, district_en, sub_ar, sub_en, "
            "city_key, city_ar, city_en, postcode, lat, lon, osm, structured FROM addresses "
            "ORDER BY id"
        ).fetchall()
        g.streets = con.execute(
            "SELECT id, name, name_ar, name_en, stype, city_key, lat, lon, minlat, minlon, "
            "maxlat, maxlon, length_m, osm FROM streets ORDER BY id"
        ).fetchall()
        g.areas = con.execute(
            "SELECT id, name_ar, name_en, kind, city_key, lat, lon, radius_m, n, source "
            "FROM areas ORDER BY id"
        ).fetchall()
        g.pois = con.execute(
            "SELECT id, name, name_ar, name_en, kind, street, city_key, hn, lat, lon, osm "
            "FROM pois ORDER BY id"
        ).fetchall()
        con.close()
        g._index()
        return g

    def _index(self) -> None:
        cache: dict[tuple, frozenset[str]] = {}

        def ck(*names):
            if names not in cache:
                cache[names] = frozenset(keys_of(*names))
            return cache[names]

        n = len(self.addr)
        self.addr_lat = np.fromiter((a[12] for a in self.addr), float, n)
        self.addr_lon = np.fromiter((a[13] for a in self.addr), float, n)
        self.addr_hn = [norm_hn(a[1]) for a in self.addr]
        for i, a in enumerate(self.addr):
            skeys = ck(a[2], a[3])
            akeys = ck(a[4], a[5]) | ck(a[6], a[7])
            self.addr_street_keys.append(skeys)
            self.addr_area_keys.append(akeys)
            for k in skeys:
                self.addr_by_street[k].append(i)
                self.addr_by_street_hn[(k, self.addr_hn[i])].append(i)
            if a[11]:
                self.addr_by_postcode[str(a[11]).strip()].append(i)

        self.street_lat = np.fromiter((s[6] for s in self.streets), float, len(self.streets))
        self.street_lon = np.fromiter((s[7] for s in self.streets), float, len(self.streets))
        for i, s in enumerate(self.streets):
            for k in ck(s[1], s[2], s[3]):
                self.street_by_key[k].append(i)
        for i, a in enumerate(self.areas):
            for k in ck(a[1], a[2]):
                self.area_by_key[k].append(i)
        for i, p in enumerate(self.pois):
            for k in ck(p[1], p[2], p[3]):
                self.poi_by_key[k].append(i)

        for c in CITIES:
            for nm in (c.en, c.ar, c.key, *c.aliases):
                k = skeleton(nm)
                if k:
                    # skeleton collisions (Dubai ~ Dibba): earlier, larger city in CITIES wins
                    self.city_by_key_alias.setdefault(k, c.key)
        # "Al Dhafra" is a region whose seat is Madinat Zayed
        for nm in ("Al Dhafra", "Al Dhafra Region", "الظفرة", "منطقة الظفرة"):
            self.city_by_key_alias[skeleton(nm)] = "madinat zayed"

        street_keys = set(self.addr_by_street) | set(self.street_by_key)
        for k in street_keys:
            if len(k) >= 3:
                self.street_coarse[coarse_key(k)].append(k)
        for k in self.area_by_key:
            if len(k) >= 3:
                self.area_coarse[coarse_key(k)].append(k)
        for k in self.poi_by_key:
            if len(k) >= 3:
                self.poi_coarse[coarse_key(k)].append(k)
        self._ambiguity()
        self.street_key_list = sorted(k for k in street_keys if len(k) >= 4)
        self.area_key_list = sorted(k for k in self.area_by_key if len(k) >= 4)
        self.poi_key_list = sorted(k for k in self.poi_by_key if len(k) >= 4)
        self.fuzzy_by_len = {
            kind: _bucket(lst)
            for kind, lst in (
                ("street", self.street_key_list),
                ("area", self.area_key_list),
                ("poi", self.poi_key_list),
            )
        }

    def _ambiguity(self) -> None:
        """Number of distinct surface names (case/space-insensitive) that share each key."""
        names: dict[str, set[str]] = defaultdict(set)
        for i, a in enumerate(self.addr):
            for nm in (a[2], a[3]):
                if nm:
                    for k in self.addr_street_keys[i]:
                        names[k].add(nm.lower())
        for s in self.streets:
            for nm in (s[1], s[2], s[3]):
                if nm:
                    for k in keys_of(nm):
                        names[k].add(nm.lower())
        self.street_ambig = {k: len(v) for k, v in names.items()}
        an: dict[str, set[str]] = defaultdict(set)
        for a in self.areas:
            for nm in (a[1], a[2]):
                if nm:
                    for k in keys_of(nm):
                        an[k].add(nm.lower())
        self.area_ambig = {k: len(v) for k, v in an.items()}
        pn: dict[str, set[str]] = defaultdict(set)
        for p in self.pois:
            for nm in (p[1], p[2], p[3]):
                if nm:
                    for k in keys_of(nm):
                        pn[k].add(nm.lower())
        self.poi_ambig = {k: len(v) for k, v in pn.items()}

    def fuzzy_pool(self, kind: str, first: str) -> list[str]:
        """Keys whose length is within about +-30% of ``n`` (edit-distance candidates)."""
        n = len(first)
        lo, hi = max(3, int(n * 0.72)), int(n * 1.4) + 1
        b = self.fuzzy_by_len.get(kind, {})
        c0 = coarse_key(first)[:1]
        out: list[str] = []
        for ln in range(lo, hi + 1):
            out += b.get((ln, c0), [])
        return out

    # ------------------------------------------------------------------ accessors
    def has_street_key(self, k: str) -> bool:
        return k in self.addr_by_street or k in self.street_by_key

    def city_name(self, key: str) -> tuple[str, str]:
        c = CITY_BY_KEY.get(key)
        return (c.en, c.ar) if c else (key, key)

    def stats(self) -> dict[str, int]:
        return {
            "addresses": len(self.addr),
            "street_segments": len(self.streets),
            "areas": len(self.areas),
            "pois": len(self.pois),
            "street_keys": len(self.street_key_list),
        }
