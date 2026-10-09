# Evaluation

All numbers come from `tahdeed eval` (raw output: [`eval_results.json`](eval_results.json), seed 7,
gazetteer snapshot 2026-10-09). Test queries are generated from **districts the models never saw**
(deterministic 50/20/30 train/calibration/test split on district hash).

## Read this first: what these numbers are and are not

- The queries are **synthetic**. Real addresses from the gazetteer are rendered with a documented
  noise model (`src/tahdeed/noise.py`): dropped fields, Arabic/English/mixed rendering, consonant and
  vowel transliteration variants, typos, abbreviations, Arabic-Indic digits, reordering, missing
  commas. The noise model is ours, not measured from real users. Real users will fail in ways it
  does not cover, so treat absolute numbers as optimistic and the *relative* comparisons and the
  calibration behaviour as the finding.
- Ground truth is the OpenStreetMap address point that the query was generated from. OSM itself can
  be wrong or offset by a few metres; "within 50 m" is a judgement against that reference.
- **Predictions were not pre-registered.** `plan.md` promised that predictions would be written
  before the run. They were not: development and evaluation overlapped (a 1,500-query probe was
  used while tuning the matcher on *train/calibration-side* districts and the heuristic baseline).
  The test districts were not used for tuning, but this is a weaker guarantee than the plan
  promised, and the numbers should be read accordingly.
- The same OSM data feeds the resolver and the Nominatim comparison, so the Nominatim row compares
  matching logic, not data. Nominatim was queried for 200 queries at ≤1 request/second with an
  identifying User-Agent.

## Headline results

| Benchmark | n | answered as *resolved* | precision@50 m of resolved | top-1 ≤50 m (forced) | ≤200 m | ≤1 km | median ms |
|---|---|---|---|---|---|---|---|
| Abu Dhabi / Al Ain / Al Dhafra, held-out districts | 6000 | 61.9% | **98.1%** | 64.6% | 69.7% | 75.3% | 4.9 |
| Same, true address removed from the index | 3000 | 49.6% | 71.0% | 37.5% | 47.5% | 57.5% | 5.0 |
| Dubai / Sharjah / Ajman POI (weaker truth) | 800 | 81.2% | 98.8% | 82.4% | 83.5% | 84.6% | 4.2 |
| Baseline: hand-set confidence rules | 1000 | 23.5% | 97.9% | 44.1% | 49.3% | 55.2% | 1.8 |

"Forced" counts the best candidate even when tahdeed would have abstained or only given an area.
"Resolved" is the stricter, confident answer.

External and naive baselines on the first 500–1000 Abu Dhabi test queries:

| System | answered | top-1 ≤50 m | ≤1 km |
|---|---|---|---|
| tahdeed (forced answer) | 100% | 64.6% | 75.3% |
| Naive fuzzy (`token_set_ratio` over address strings, candidates pre-filtered by house number: generous to the baseline) | 84.8% | 54.8% | 57.8% |
| Public Nominatim, `countrycodes=ae` (n=200) | 54.0% | 45.0% | 51.5% |

## Calibration

The confidence is only useful if it means what it says.

- ECE of the within-50 m probability on all fine candidates: **0.020**. Of the "right at its own
  tier" probability: 0.050.
- Reliability, high end: candidates scored 0.9–1.0 are within 50 m 99.0% of the time (n=3360);
  0.8–0.9: 95.6% (n=250). Mid-range bins are noisy (n of 14–120 each) and slightly *under*-confident
  in places; the 0.5–0.6 bin is over-confident (43% observed).

Selective prediction (answer the most confident first):

| Coverage | 10% | 30% | 50% | 60% | 70% | 80% | 100% |
|---|---|---|---|---|---|---|---|
| Precision ≤50 m | 100% | 99.3% | 99.3% | 98.9% | 93.5% | 82.4% | 65.9% |

The operating point (≥95% precision on the calibration split) lands near 60–62% coverage, which is
where the curve starts to fall.

## What breaks (failure analysis)

1. **Missing house number (`drop_hn`)**: never resolved to a building, correctly (0.3% "resolved").
   Within 50 m only 12% of the time, which is the honest answer: a street is not a point. 68%
   land within 1 km. These cases return "add the building number".
2. **Consonant-changing transliteration** (`kh→k`, `q→g`, `j→y`…) is the weakest noise: only 46%
   resolved and 45% top-1. Vowel variants are absorbed by the skeleton keys (55% resolved); the
   consonant classes handled by the coarse key help but do not cover everything.
3. **Coverage hole**: when the true address is not in the registry the system should degrade to a
   coarser tier. It does so only partly: 49.6% are still "resolved" and only 71.0% of those are
   within 50 m, meaning in about 29% of those cases a neighbouring building (same street, other
   house number or sub-sector) is returned with high confidence. This is the largest known
   weakness; the training set only contained 15% hidden-truth queries.
4. **Tier validity of approximate answers**: when the answer is an area or street, the named
   place is correct 64% of the time (all noise included); the stated radius covers the true point
   for 64% of approximate answers overall, and ≈90% *conditional on the place being right*, which
   is how the radius is defined. A user reads the radius as "if this place is right".
5. **Short skeleton collisions**: three-consonant keys collide across unrelated names ("Dubai" and
   "Dibba" share a skeleton; "asdf" matches "Sadaf"). One real bug of this kind (Dubai resolving to
   a village near Dibba) was found by hand and fixed; others likely remain.
6. **Dubai**: OSM has very few structured Dubai addresses, so Dubai is evaluated on POI
   name + street queries only. This is a different and easier task than address resolution and
   must not be read as "Dubai addresses work at 98%".
7. **Latency**: median 5 ms, p95 7 ms per query on 2 CPU cores, after a ~7 s / ~420 MB load.

## Per-noise-type results (Abu Dhabi, top-1 ≤50 m / resolved)

| Noise | n | resolved | top-1 ≤50 m |
|---|---|---|---|
| English only | 3353 | 58% | 60% |
| Arabic only | 1439 | 68% | 70% |
| Mixed | 1208 | 65% | 69% |
| Arabic-Indic digits | 1874 | 66% | 69% |
| Building keyword (villa, no.) | 1353 | 74% | 75% |
| Number after the street | 653 | 45% | 53% |
| No commas | 2399 | 55% | 58% |
| Typos | 1608 | 56% | 58% |
| Abbreviations | 1088 | 60% | 63% |
| Dropped district | 2091 | 58% | 62% |
| Dropped city | 1823 | 60% | 64% |
| Consonant transliteration | 542 | 46% | 45% |

Arabic queries do better than English ones because the registry's Arabic spelling is canonical,
while English transliteration of the same name varies.
