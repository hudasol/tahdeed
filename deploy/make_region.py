"""Cut a regional gazetteer out of the full one, to fit a small-memory host.

    python deploy/make_region.py data/gazetteer.sqlite data/region/gazetteer.sqlite --preset north
    python deploy/make_region.py FULL.sqlite OUT.sqlite --cities "abu dhabi,al ain"

Keeps every row whose ``city_key`` is in the region, in all four tables, plus the ``meta`` rows (with
a ``region`` row added). Row ids are preserved. The output is a normal gazetteer (same schema), so
the service and ``tahdeed train`` work on it unchanged.

The gazetteer's sha256 is the hash of the file, so a regional file needs its OWN model:

    tahdeed train --db OUT.sqlite --out OUT_DIR/ranker.npz     # needs `pip install ".[train]"`

and the figures in docs/EVALUATION.md describe the full database, not the region. Queries for places
outside the region cannot be answered (they fall back to the nearest listed city or abstain).

Licence: the output is a Derived Database under the ODbL, exactly like the full file; see
docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

TABLES = ("addresses", "streets", "areas", "pois")
PRESETS = {
    # Dubai + Sharjah + Ajman (the three emirates the task names) and their small dependencies
    "north": ["dubai", "hatta", "sharjah", "khor fakkan", "kalba", "ajman"],
    # the whole emirate of Abu Dhabi
    "abu-dhabi-emirate": ["abu dhabi", "al ain", "ruwais", "madinat zayed", "liwa"],
    # Abu Dhabi city alone
    "abu-dhabi-city": ["abu dhabi"],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset", choices=sorted(PRESETS))
    g.add_argument("--cities", help="comma-separated city_key values, e.g. 'dubai,sharjah'")
    a = ap.parse_args(argv)

    cities = (
        PRESETS[a.preset] if a.preset else [c.strip() for c in a.cities.split(",") if c.strip()]
    )
    if a.dst.exists():
        sys.exit(f"{a.dst} exists; refusing to overwrite")
    a.dst.parent.mkdir(parents=True, exist_ok=True)

    s = sqlite3.connect(f"file:{a.src}?mode=ro", uri=True)
    d = sqlite3.connect(a.dst)
    marks = ",".join("?" * len(cities))
    for (sql,) in s.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
    ):
        d.execute(sql)
    for t in TABLES:
        cols = [r[1] for r in s.execute(f"PRAGMA table_info({t})")]
        rows = s.execute(f"SELECT * FROM {t} WHERE city_key IN ({marks})", cities).fetchall()
        d.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(cols))})", rows)
        total = s.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:10s} {len(rows):>8} of {total:>8} ({100 * len(rows) / max(total, 1):.1f}%)")
    d.executemany("INSERT INTO meta VALUES (?,?)", s.execute("SELECT k, v FROM meta").fetchall())
    d.execute("INSERT OR REPLACE INTO meta VALUES ('region', ?)", (",".join(cities),))
    d.commit()
    d.execute("VACUUM")
    d.close()
    print(f"wrote {a.dst} ({a.dst.stat().st_size / 1e6:.1f} MB) for: {', '.join(cities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
