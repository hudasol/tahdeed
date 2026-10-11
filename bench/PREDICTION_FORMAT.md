# Prediction file format

JSON Lines, one object per query `id` in `bench/data/*.jsonl`. Unknown ids and duplicate ids are errors.
Missing ids count as abstentions.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | row id, e.g. `address_dev-00012` |
| `lat`, `lon` | number | no | predicted coordinate (WGS84). Omit when you have nothing |
| `abstain` | boolean | no | `true` = "I do not answer". Default `false` if `lat/lon` present, else treated as abstain |
| `confidence` | number in [0,1] | no | your P(within 50 m of truth). Used only for calibration (ECE) |
| `city` | string | no | answered city key (lower-case key such as `abu dhabi`, `dubai`, `al ain`, `sharjah`; the 15 keys are listed in `src/tahdeed/geo.py`), compared with the truth record's city tag |

An abstaining row may still carry `lat/lon`: those rows are used only for the *forced* metrics.

```
{"id": "address_dev-00000", "lat": 24.4539, "lon": 54.3773, "confidence": 0.93}
{"id": "address_dev-00001", "lat": 24.47, "lon": 54.36, "abstain": true, "confidence": 0.12}
{"id": "address_dev-00002", "abstain": true}
```

## Metrics (all with Wilson 95% intervals)

- **answered** = non-abstaining / n.
- **precision@r** (r = 50, 200, 1000 m) = within r of truth, among answered.
- **wrong city** = answered city ≠ truth city, among answered; the *confident-wrong-city rate*. If you give `city`, it is compared with the truth record's city tag (`truth_city`). If not, the nearest city centre of your coordinate is compared with the nearest city centre of the truth coordinate (`truth_city_geo`). The geometric version misclassifies points near city edges (e.g. Abu Dhabi suburbs): supply `city` if you can.
- **end-to-end@50** = within 50 m / n, abstentions count as misses.
- **forced@r** = within r of truth over all n, using `lat/lon` even where abstaining.
- **ECE** = expected calibration error of `confidence` against the within-50 m indicator, answered rows only.
- Cross-city sets also report each stratum/evidence cell (E0 street+number, E1 + district, E2 + city).
