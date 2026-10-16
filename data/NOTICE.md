# Data notice

tahdeed's gazetteer is derived from OpenStreetMap data.

© OpenStreetMap contributors. Data available under the Open Database License (ODbL) 1.0:
https://www.openstreetmap.org/copyright

- Source extract: United Arab Emirates, via download.openstreetmap.fr (snapshot dated 2026-10-09).
- The full derived database is built locally (`tahdeed build`) and is not committed.
- Any small fixture committed under `tests/fixtures/` is an attributed excerpt of the same data and remains under ODbL.

## Optional supplements (not distributed)

The repository contains scripts that fetch Overture Places (`scripts/fetch_overture_dubai.py`) and
use GeoNames `AE` (`scripts/eval_supplements.py`) for evaluation only. No row from either source is
committed or merged into the gazetteer. If a future build merges them, the combined database stays
under ODbL 1.0 and must carry, in addition to the OpenStreetMap notice above: "Contains data from
Overture Maps Foundation Places (CDLA Permissive 2.0; Foursquare data Apache 2.0, Copyright 2024
Foursquare Labs, Inc.; AllThePlaces CC0 1.0)" with Overture's NOTICE file, and "GeoNames
(geonames.org), CC BY 4.0".
