"""Count OSM address records last edited after a cutoff (candidate pool for a fresh sealed set).

    python scripts/fresh_records.py extract.osm.pbf --after 2026-10-09T00:57:00Z [--json out.json]

An address record is a node or way with ``addr:housenumber`` and ``addr:street``. Reported: how
many exist, how many carry a timestamp after the cutoff, and how many of those fall in the Abu
Dhabi emirate bounding box (where OSM addresses are structured). It reads tags and timestamps
only, prints counts only, and never writes a query or an address.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import osmium

ABU_DHABI_BBOX = (51.5, 22.6, 56.0, 24.9)  # lon_min, lat_min, lon_max, lat_max (approximate)


class Counter(osmium.SimpleHandler):
    def __init__(self, cutoff: datetime) -> None:
        super().__init__()
        self.cutoff = cutoff
        self.total = self.fresh = self.fresh_ad = self.no_ts = 0
        self.fresh_created = 0  # version 1 after the cutoff: a record that did not exist before

    def _seen(self, o, lon: float | None, lat: float | None) -> None:
        t = o.tags
        if "addr:housenumber" not in t or "addr:street" not in t:
            return
        self.total += 1
        ts = o.timestamp
        if ts is None or ts.year < 2000:
            self.no_ts += 1
            return
        if ts > self.cutoff:
            self.fresh += 1
            if o.version == 1:
                self.fresh_created += 1
            if (
                lon is not None
                and ABU_DHABI_BBOX[0] <= lon <= ABU_DHABI_BBOX[2]
                and (ABU_DHABI_BBOX[1] <= lat <= ABU_DHABI_BBOX[3])
            ):
                self.fresh_ad += 1

    def node(self, n) -> None:
        loc = n.location
        self._seen(n, loc.lon if loc.valid() else None, loc.lat if loc.valid() else None)

    def way(self, w) -> None:
        try:
            nd = w.nodes[0]
            lon, lat = (nd.lon, nd.lat) if nd.location.valid() else (None, None)
        except Exception:
            lon = lat = None
        self._seen(w, lon, lat)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("--after", required=True, help="ISO timestamp, e.g. 2026-10-09T00:57:00Z")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    cutoff = datetime.fromisoformat(a.after.replace("Z", "+00:00")).astimezone(UTC)
    h = Counter(cutoff)
    h.apply_file(a.pbf, locations=True)
    out = {
        "extract": a.pbf,
        "cutoff": cutoff.isoformat(),
        "address_records": h.total,
        "without_timestamp": h.no_ts,
        "edited_after_cutoff": h.fresh,
        "created_after_cutoff": h.fresh_created,
        "edited_after_cutoff_abu_dhabi_bbox": h.fresh_ad,
    }
    print(json.dumps(out, indent=1))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
