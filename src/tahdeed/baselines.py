"""Real baselines for Gulf-AddressBench, each writing the prediction JSONL of
``bench/PREDICTION_FORMAT.md``.

    tahdeed bench baselines {tfidf,bm25,libpostal,photon,nominatim} --data DIR --out FILE

* ``tfidf``: character 3 to 4 gram TF-IDF nearest neighbour over gazetteer address and POI strings
  (the implementation in :mod:`tahdeed.studies`, extended to index POIs).
* ``bm25``: Okapi BM25 over the same strings, tokens from :func:`tahdeed.normalize.tokenize`
  (Arabic unification, Latin casefolding, ASCII digits).
* ``libpostal``: libpostal parse, then an exact lookup in the gazetteer. Needs the ``postal`` Python
  package with the libpostal library and model; when they are missing the command stops with an error
  rather than emitting a stand in.
* ``photon`` (photon.komoot.io) and ``nominatim`` (nominatim.openstreetmap.org): public geocoders,
  used within their fair use terms: at most one request per second, an identifying User-Agent, a small
  even stride sample, responses cached so a re run asks for nothing. Their output is a competitor,
  never ground truth. Commercial geocoders are not used.

TF-IDF, BM25 and libpostal answer whenever they find a candidate (no abstention, no confidence). Hole
rows (truth record absent from the index) are handled by removing that record from the index; Photon
and Nominatim cannot do that and skip hole rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .bench import DATA, _write_preds, load_rows, read_predictions
from .geo import haversine_m
from .normalize import skeleton, tokenize

USER_AGENT = "tahdeed-bench/1.0 (+https://github.com/hudasol/tahdeed)"
UAE_BBOX = "51.0,22.4,56.6,26.2"  # lon W, lat S, lon E, lat N
MIN_GAP_S = 1.1  # public services: at most one request per second
SYSTEMS = ["tfidf", "bm25", "libpostal", "photon", "nominatim"]


# ----------------------------------------------------------------------------- index baselines


class Bm25:
    """Okapi BM25 (k1=1.5, b=0.75) over a list of texts."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        post: dict[str, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
        lens = np.zeros(len(docs), dtype=np.float32)
        for i, d in enumerate(docs):
            toks = tokenize(d)
            lens[i] = len(toks)
            for t, c in Counter(toks).items():
                post[t][0].append(i)
                post[t][1].append(c)
        self.idx = {t: np.asarray(v[0], dtype=np.int32) for t, v in post.items()}
        self.tf = {t: np.asarray(v[1], dtype=np.float32) for t, v in post.items()}
        self.dl, self.k1, self.b, self.n = lens, k1, b, len(docs)
        self.avg = float(lens.mean()) if len(docs) else 1.0

    def scores(self, text: str) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for t in set(tokenize(text)):
            d = self.idx.get(t)
            if d is None:
                continue
            tf = self.tf[t]
            idf = math.log(1.0 + (self.n - len(d) + 0.5) / (len(d) + 0.5))
            s[d] += (
                idf
                * tf
                * (self.k1 + 1)
                / (tf + self.k1 * (1 - self.b + self.b * self.dl[d] / self.avg))
            )
        return s


def _best(scores: np.ndarray, exclude: int | None) -> int | None:
    if exclude is not None:
        scores = scores.copy()
        scores[exclude] = -1.0
    i = int(np.argmax(scores))
    return i if scores[i] > 0 else None


def _answer(row_id: str, meta: tuple | None) -> dict:
    if meta is None:
        return {"id": row_id, "abstain": True}
    out = {"id": row_id, "lat": float(meta[0]), "lon": float(meta[1])}
    if meta[2]:
        out["city"] = meta[2]
    return out


def run_ranker(system: str, rows: list[dict], db: str) -> list[dict]:
    """TF-IDF or BM25 over address + POI strings; the hole row's truth record is excluded."""
    from .gazetteer import Gazetteer
    from .studies import TfidfBaseline, gazetteer_docs

    g = Gazetteer.load(db)
    model: TfidfBaseline | Bm25
    if system == "tfidf":
        model = TfidfBaseline(g, include_pois=True)
        meta = model.meta
    else:
        docs, meta = gazetteer_docs(g, include_pois=True)
        model = Bm25(docs)
    pos = {m[3]: i for i, m in enumerate(meta)}
    out = []
    for r in rows:
        ex = pos.get(r["truth_ref"]) if r.get("hole") else None
        i = _best(model.scores(r["text"]), ex)
        out.append(_answer(r["id"], None if i is None else meta[i]))
    return out


# ----------------------------------------------------------------------------- libpostal


def have_libpostal() -> bool:
    try:
        import postal.parser  # noqa: F401
    except Exception:
        return False
    return True


def lookup_parsed(
    parsed: list[tuple[str, str]], g, exclude: set[tuple[str, int]] | None = None
) -> tuple | None:
    """Exact lookup of a libpostal parse in the gazetteer.

    ``parsed`` is libpostal's list of (value, label). A street + house number is looked up in the
    address index, else a place name (label ``house``) in the POI index. A city, when parsed, must
    match the candidate's city. Candidates that disagree by more than 200 m are ambiguous: abstain.
    Returns ``(lat, lon, city_key)`` or None."""
    from .gazetteer import keys_of, norm_hn

    lab: dict[str, str] = {}
    for value, label in parsed:
        lab[label] = f"{lab[label]} {value}" if label in lab else value
    city = g.city_by_key_alias.get(skeleton(lab["city"])) if lab.get("city") else None
    cands: list[tuple[float, float, str]] = []
    if lab.get("road") and lab.get("house_number"):
        hn = norm_hn(lab["house_number"])
        ids = {i for k in keys_of(lab["road"]) for i in g.addr_by_street_hn.get((k, hn), ())}
        cands = [(g.addr[i][12], g.addr[i][13], g.addr[i][8]) for i in sorted(ids)
                 if not (exclude and ("a", i) in exclude)]  # fmt: skip
    if not cands and lab.get("house"):
        ids = {i for k in keys_of(lab["house"]) for i in g.poi_by_key.get(k, ())}
        cands = [(g.pois[i][8], g.pois[i][9], g.pois[i][6]) for i in sorted(ids)
                 if not (exclude and ("p", i) in exclude)]  # fmt: skip
    if city:
        cands = [c for c in cands if c[2] == city]
    if not cands:
        return None
    if any(haversine_m(cands[0][0], cands[0][1], c[0], c[1]) > 200 for c in cands[1:]):
        return None
    return cands[0]


def run_libpostal(rows: list[dict], db: str) -> list[dict]:
    if not have_libpostal():
        raise RuntimeError(
            "libpostal is not available: the `postal` Python package needs the libpostal C library "
            "and its model data (about 2 GB), which could not be installed. Not simulated."
        )
    from postal.parser import parse_address

    from .gazetteer import Gazetteer

    g = Gazetteer.load(db)
    by_a = {a[14]: i for i, a in enumerate(g.addr)}
    by_p = {p[10]: i for i, p in enumerate(g.pois)}
    out = []
    for r in rows:
        ex = None
        if r.get("hole") and r.get("truth_ref"):
            kind, osm = r["truth_ref"].split("/", 1)
            idx = (by_a if kind == "addr" else by_p).get(osm)
            ex = {("a" if kind == "addr" else "p", idx)} if idx is not None else None
        hit = lookup_parsed(list(parse_address(r["text"])), g, ex)
        out.append(_answer(r["id"], hit))
    return out


# ----------------------------------------------------------------------------- public geocoders


def _fetch_json(url: str):
    """One GET with the identifying User-Agent; backs off on 429 and 5xx, never faster than the
    caller's throttle. Module level so tests can replace it."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return json.load(resp)
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            ra = ex.headers.get("Retry-After", "")
            time.sleep(float(ra) if ra.isdigit() else 30.0 * 2**attempt)
    return None


def photon_url(text: str) -> str:
    q = {"q": text, "limit": 1, "bbox": UAE_BBOX}
    return "https://photon.komoot.io/api/?" + urllib.parse.urlencode(q)


def nominatim_url(text: str) -> str:
    q = {"q": text, "format": "jsonv2", "limit": 1, "countrycodes": "ae"}
    return "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(q)


def _first_point(system: str, data) -> list[float] | None:
    if system == "photon":
        feats = (data or {}).get("features") or []
        if feats:
            lon, lat = feats[0]["geometry"]["coordinates"][:2]
            return [float(lat), float(lon)]
        return None
    if data:
        return [float(data[0]["lat"]), float(data[0]["lon"])]
    return None


def run_public(
    system: str, rows: list[dict], cache: Path | None, gap: float = MIN_GAP_S
) -> list[dict]:
    """Photon or Nominatim for the given rows (already sampled by the caller)."""
    url_of = photon_url if system == "photon" else nominatim_url
    store: dict = json.loads(cache.read_text(encoding="utf-8")) if cache and cache.exists() else {}
    last, new, out = 0.0, 0, []
    for r in rows:
        key = f"{r['id']}|{hashlib.sha1(r['text'].encode()).hexdigest()[:8]}"
        if key not in store:
            wait = last + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            store[key] = _first_point(system, _fetch_json(url_of(r["text"])))
            new += 1
            if cache and new % 10 == 0:
                cache.write_text(json.dumps(store), encoding="utf-8")
                print(f"{system}: {new} new requests", flush=True)
        pt = store[key]
        out.append(
            {"id": r["id"], "lat": pt[0], "lon": pt[1]} if pt else {"id": r["id"], "abstain": True}
        )
    if cache and new:
        cache.write_text(json.dumps(store), encoding="utf-8")
    return out


# ----------------------------------------------------------------------------- CLI


def stride_sample(rows: list[dict], limit: int) -> list[dict]:
    """Even stride over the non-hole rows of each set, in file order (deterministic)."""
    out = []
    for name in sorted({r["set"] for r in rows}):
        allr = [r for r in rows if r["set"] == name and not r["hole"]]
        out += allr[:: max(1, len(allr) // limit)][:limit]
    return out


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("baselines", help="run a real baseline and write a prediction file")
    p.add_argument("system", choices=SYSTEMS)
    p.add_argument("--set", action="append", default=None, help="dataset name (repeatable)")
    p.add_argument("--data", default=str(DATA))
    p.add_argument("--db", default="data/gazetteer.sqlite")
    p.add_argument("--limit", type=int, default=150, help="photon, nominatim: rows per set")
    p.add_argument(
        "--ids-of",
        default=None,
        help="photon, nominatim: use exactly the ids in this prediction file",
    )
    p.add_argument(
        "--cache", default=None, help="photon, nominatim: response cache (default: next to --out)"
    )
    p.add_argument("--out", required=True)


def run(a: argparse.Namespace) -> int:
    rows = load_rows(Path(a.data), a.set)
    try:
        if a.system in ("tfidf", "bm25"):
            preds = run_ranker(a.system, rows, a.db)
        elif a.system == "libpostal":
            preds = run_libpostal(rows, a.db)
        else:
            if a.ids_of:
                keep = set(read_predictions(a.ids_of))
                sample = [r for r in rows if r["id"] in keep and not r["hole"]]
            else:
                sample = stride_sample(rows, a.limit)
            cache = Path(a.cache) if a.cache else Path(a.out).with_suffix(".cache.json")
            preds = run_public(a.system, sample, cache)
    except RuntimeError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 3
    _write_preds(preds, a.out)
    print(f"wrote {len(preds)} predictions to {a.out}")
    return 0
