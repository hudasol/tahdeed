"""Cut a small bbox excerpt of the gazetteer (Al Khalidiyah / Al Markaziyah) for CI tests."""

import sqlite3
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "data/gazetteer.sqlite"
dst = sys.argv[2] if len(sys.argv) > 2 else "tests/fixtures/mini.sqlite"
S, N, W, E = 24.455, 24.495, 54.320, 54.380

s = sqlite3.connect(src)
d = sqlite3.connect(dst)
for (sql,) in s.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
    d.execute(sql)
for t, lat, lon in (("addresses", "lat", "lon"), ("streets", "lat", "lon"),
                    ("areas", "lat", "lon"), ("pois", "lat", "lon")):  # fmt: skip
    cols = [r[1] for r in s.execute(f"PRAGMA table_info({t})")]
    q = f"SELECT * FROM {t} WHERE {lat} BETWEEN ? AND ? AND {lon} BETWEEN ? AND ?"
    rows = s.execute(q, (S, N, W, E)).fetchall()
    d.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(cols))})", rows)
    print(t, len(rows))
d.executemany("INSERT INTO meta VALUES (?,?)", s.execute("SELECT k, v FROM meta").fetchall())
d.execute(
    "INSERT OR REPLACE INTO meta VALUES ('note', 'CI fixture: bbox excerpt, (c) OpenStreetMap contributors, ODbL')"
)
d.commit()
d.execute("VACUUM")
d.close()
