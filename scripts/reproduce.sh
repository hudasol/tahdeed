#!/usr/bin/env bash
# Rebuild everything from an OSM extract and regenerate every table and figure.
#   bash scripts/reproduce.sh path/to/united_arab_emirates.osm.pbf
# Fixed seeds throughout; the environment (python, numpy, rapidfuzz) is recorded in docs/studies.json.
set -euo pipefail
PBF="${1:?usage: reproduce.sh <extract.osm.pbf>}"
export OMP_NUM_THREADS=1
tahdeed build "$PBF" --out data/gazetteer.sqlite
tahdeed verify || true                       # no model yet: expected to report FAIL on first run
tahdeed train --hole-rate 0.30 --out data/models/ranker.npz
tahdeed train --hole-rate 0.00 --out data/models/ranker_h0.npz     # ablation only
tahdeed verify
tahdeed eval --n 6000 --out docs/eval.json
tahdeed studies --n 2500 --h0 data/models/ranker_h0.npz --out docs/studies.json
tahdeed gold --out docs/gold.json
# The sealed split is read once per release decision (docs/SEALED2.md). Set TAHDEED_ALLOW_SEALED=1 to overwrite docs/sealed.
if [ "${TAHDEED_ALLOW_SEALED:-0}" = "1" ]; then
  TAHDEED_SPLIT=sealed tahdeed eval --n 6000 --out docs/sealed/eval.json
  TAHDEED_SPLIT=sealed tahdeed studies --n 2500 --h0 data/models/ranker_h0.npz --out docs/sealed/studies.json
fi
tahdeed figures
python scripts/make_evaluation_md.py
tahdeed bench --n 2000
