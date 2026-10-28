# Gulf-AddressBench

A small, versioned benchmark for **free-text address → coordinate** resolution in the UAE, with the
property that matters in practice: a system may **abstain**, and a confident answer in the wrong place
(or the wrong city) is worse than no answer. Results live in [`docs/BENCH_REPORT.md`](../docs/BENCH_REPORT.md).

## Task

Input: one text string (English, Arabic, Arabizi or mixed). Output: a coordinate, optionally with
`abstain: true` and a `confidence` = P(answer is within 50 m of truth). No gazetteer is supplied; a
participant may use any open data (OpenStreetMap is the natural choice and is what the truth comes
from; see limitations).

## Contents

| Path | What |
|---|---|
| `data/*.jsonl` | the OpenStreetMap derived, synthetic sets (one JSON object per line, truth included) |
| `data_external/` | two sets whose text and truth are **not** OpenStreetMap (Overture Places, Wikidata); own manifest and `NOTICE.md`, not ODbL |
| `data/MANIFEST.json` | version, per-set counts, seeds, SHA-256, contamination status |
| `DATA_CARD.md` | construction, licences, attribution, limitations |
| `SPLITS.md` | split policy and **which sets were seen during development** |
| `PREDICTION_FORMAT.md` | the prediction-file format and metric definitions |
| `results/` | prediction and score files for the baselines on `data/` |
| `results_external/` | the same for `data_external/` |
| `human_kit/` | collection kit for the human-written set (no data yet) |

## Use

```
tahdeed bench score my_predictions.jsonl              # prints metrics with 95% intervals
tahdeed bench score my_predictions.jsonl --set address_sealed --json score.json
tahdeed bench baseline tahdeed --out preds.jsonl      # reference system (needs gazetteer + model)
tahdeed bench build                                   # regenerate the data from the gazetteer
```

Scoring needs only the data directory; it does not need the gazetteer or any Tahdeed model.

## Independent real text sets and real baselines

```
tahdeed bench fetch-external                     # rebuild bench/data_external (Overture release pinned in the code; needs `pip install -e .[external]`)
tahdeed bench baselines tfidf --data bench/data_external --out preds.jsonl      # also: bm25, libpostal, photon, nominatim
tahdeed bench baseline tahdeed --data bench/data_external --out preds.jsonl
tahdeed bench score preds.jsonl --data bench/data_external
```

`bench/data_external` holds `overture_places` (business written name and address strings) and
`wikidata_addresses` (editor written). The text is not generated from OpenStreetMap and the truth is the
source's coordinate, which can be wrong; see `DATA_CARD.md`. Baselines (`src/tahdeed/baselines.py`):
TF-IDF character 3 to 4 grams and BM25 over the gazetteer's address and POI strings, libpostal parse with exact lookup,
and the public Photon and Nominatim services within their fair use limits (one request per second,
identifying User-Agent, even stride samples of at most 150 rows per set, cached). Tables are in
[`docs/BENCH_REPORT.md`](../docs/BENCH_REPORT.md), generated from the score files.

**libpostal was not run.** The `postal` Python package needs the libpostal C library and about 2 GB of
model data. In the build environment the library source host timed out, the model data host answered
HTTP 403, and no prebuilt package exists on PyPI, so it could not be installed. The code path
(`baselines.lookup_parsed`, unit tested with a stubbed parse) refuses to run without the library
instead of producing stand in output. Anyone with libpostal installed can run it with the command above.

## Rules for fair comparison

1. Do not tune on `*_sealed` sets, on `gold_handwritten` or on anything in `data_external`. Report which sets you used for tuning.
2. Hole sets (`hole_*`): the row's `truth_ref` OSM element is **absent from the reference index**. A system whose index contains it cannot be compared on these rows; say so rather than reporting the number.
3. Never use another geocoder's output as truth.
4. Report intervals (the scorer does) and the sample size.
5. Keep the licences apart: `data/` is ODbL (OpenStreetMap derived); `data_external/` is not, and its rows must not be merged into the ODbL files.
