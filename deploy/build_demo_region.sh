#!/usr/bin/env bash
# Reproducible Abu Dhabi emirate demo build (reduced region for a 512 MB free instance).
#   bash deploy/build_demo_region.sh data/gazetteer.sqlite region
# Produces region/gazetteer.sqlite, region/gazetteer.sqlite.gz, region/ranker.npz (trained on that
# exact file, so TAHDEED_STRICT=1 accepts it), region/SHA256SUMS and docs/region_rss.json (real
# VmRSS/VmHWM from /proc/self/status; Linux only). Nothing is uploaded or deployed.
set -euo pipefail
SRC="${1:?usage: build_demo_region.sh <full gazetteer.sqlite> <out dir>}"
OUT="${2:?usage: build_demo_region.sh <full gazetteer.sqlite> <out dir>}"
export OMP_NUM_THREADS=1
mkdir -p "$OUT"
python deploy/make_region.py "$SRC" "$OUT/gazetteer.sqlite" --preset abu-dhabi-emirate
tahdeed train --db "$OUT/gazetteer.sqlite" --out "$OUT/ranker.npz" --workers "${WORKERS:-2}"
TAHDEED_STRICT=1 python deploy/measure_rss.py --db "$OUT/gazetteer.sqlite" \
  --model "$OUT/ranker.npz" --out docs/region_rss.json
gzip -kf "$OUT/gazetteer.sqlite"
(cd "$OUT" && sha256sum gazetteer.sqlite gazetteer.sqlite.gz ranker.npz > SHA256SUMS)
cat "$OUT/SHA256SUMS"
