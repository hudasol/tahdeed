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
| `data/*.jsonl` | the sets (one JSON object per line, truth included) |
| `data/MANIFEST.json` | version, per-set counts, seeds, SHA-256, contamination status |
| `DATA_CARD.md` | construction, licences, attribution, limitations |
| `SPLITS.md` | split policy and **which sets were seen during development** |
| `PREDICTION_FORMAT.md` | the prediction-file format and metric definitions |
| `results/` | prediction and score files for the baselines |
| `human_kit/` | collection kit for the human-written set (no data yet) |

## Use

```
tahdeed bench score my_predictions.jsonl              # prints metrics with 95% intervals
tahdeed bench score my_predictions.jsonl --set address_sealed --json score.json
tahdeed bench baseline tahdeed --out preds.jsonl      # reference system (needs gazetteer + model)
tahdeed bench build                                   # regenerate the data from the gazetteer
```

Scoring needs only `bench/data`; it does not need the gazetteer or any Tahdeed model.

## Rules for fair comparison

1. Do not tune on `*_sealed` sets or on `gold_handwritten`. Report which sets you used for tuning.
2. Hole sets (`hole_*`): the row's `truth_ref` OSM element is **absent from the reference index**. A system whose index contains it cannot be compared on these rows; say so rather than reporting the number.
3. Never use another geocoder's output as truth.
4. Report intervals (the scorer does) and the sample size.
