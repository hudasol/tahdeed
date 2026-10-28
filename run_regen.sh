set -e
export OMP_NUM_THREADS=1
tahdeed train --hole-rate 0.00 --out data/models/ranker_h0.npz
tahdeed eval --n 6000 --out docs/eval.json
tahdeed studies --n 2500 --h0 data/models/ranker_h0.npz --out docs/studies.json
tahdeed gold --out docs/gold.json
touch regen.done
