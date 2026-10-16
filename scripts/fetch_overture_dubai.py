"""Fetch Overture Places rows in a Dubai bounding box to a local JSON-lines file (T4).

    python scripts/fetch_overture_dubai.py --release 2026-09-23.1 --out supp/overture_dubai.jsonl

Needs ``duckdb`` (not a tahdeed dependency; install it in a separate environment). Reads the public
bucket with HTTP range requests filtered by bounding box. Keeps id, primary name, common English
and Arabic names, confidence, the source datasets and their licences, and the point. The output is
local working data and is not committed; Overture Places sources are CDLA Permissive 2.0,
Apache 2.0 or CC0 1.0 (see docs/DATA_SOURCES.md).
"""

from __future__ import annotations

import argparse
import json

import duckdb

BBOX = (54.9, 24.75, 55.65, 25.45)  # lon/lat W,S,E,N


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    w, s, e, n = BBOX
    path = f"s3://overturemaps-us-west-2/release/{a.release}/theme=places/type=place/*"
    q = f"""
      SELECT id, names.primary AS name, names.common['en'] AS name_en, names.common['ar'] AS name_ar,
             confidence, to_json(sources) AS sources,
             (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat
      FROM read_parquet('{path}', hive_partitioning=1)
      WHERE bbox.xmin >= {w} AND bbox.xmax <= {e} AND bbox.ymin >= {s} AND bbox.ymax <= {n}
    """
    rows = con.execute(q).fetchall()
    cols = ["id", "name", "name_en", "name_ar", "confidence", "sources", "lon", "lat"]
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            d = dict(zip(cols, r, strict=True))
            d["sources"] = json.loads(d["sources"]) if d["sources"] else []
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"{len(rows)} rows -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
