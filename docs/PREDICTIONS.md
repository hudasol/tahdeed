# Predictions, written before each run

Rule: a prediction is committed **before** the evaluation that tests it. Results go in the table next
to it afterwards, hit or miss. `dev` is the iteration split; `sealed` is only used for the v1.0 baseline
and the final report. (v1.0 was evaluated on the old combined test split, which is dev + sealed.)

## Round 1 (after Google review upgrades), dev split, hole mix 30% in training

| # | Prediction | Basis | Result |
|---|---|---|---|
| P1.1 | Hole benchmark (truth removed): precision of *resolved* rises from 71% to at least 85% | district-conflict feature + 30% hole training mix | **Near miss**: 83.7% (95% CI 81.7-85.7%); was 71.0% |
| P1.2 | Hole benchmark: resolved share falls below 35% (the system should abstain more) | same | **Miss**: 46.2% resolved (was 49.6%). The system abstains only a little more under holes; the gain came mostly from fewer wrong answers |
| P1.3 | Normal benchmark (no holes): resolved precision stays at or above 96.5%; resolved share drops by no more than 8 points (from 61.9%) | price of caution | **Hit**: 98.2% precision (CI 97.8-98.7%); resolved share *rose* 61.9% → 64.5% (the retrieval fixes outweighed the caution) |
| P1.4 | Consonant-variant queries: top-1 within 50 m rises from 45% to at least 55% | short keys + sibling keys + full-name fuzzy spans | **Miss**: 49.8% top-1 ≤50 m (was 45%). Better, not enough |
| P1.5 | ECE of P(within 50 m) stays at or below 0.03 on the 30%-hole mixture | isotonic on matching mixture | **Hit**: ECE 0.021 on the no-hole benchmark, 0.010 on the 30% mix |
| P1.6 | ECE of P(within 1 km) at or below 0.05 | new head | **Hit**: ECE 0.015 |
| P1.7 | Median latency stays under 15 ms (was 5 ms) | wider span generation | **Hit**: median 8.7 ms, p95 15.3 ms |

Hole sensitivity of the Round 1 model (dev split, 1,500 queries per row):

| Share of queries whose true address is absent | resolved | precision@50 m of resolved | forced top-1 ≤50 m | ECE P(≤50 m) |
|---|---|---|---|---|
| 0% | 65.1% | 97.6% | 67.4% | 0.021 |
| 15% | 61.8% | 95.7% | 62.5% | 0.015 |
| 30% (training mix) | 59.1% | 94.3% | 58.8% | 0.010 |
| 50% | 55.2% | 91.8% | 53.4% | 0.015 |
| 100% | 46.5% | 84.0% | 41.0% | 0.049 |

Reading: calibration holds across the whole range (ECE ≤ 0.05) but *precision cannot*: if every
query is for an absent address, 16% of confident answers are wrong neighbours. That is a limit of
the data, now quantified instead of hidden.

## Round 2 (after Edge review upgrades)

Written while the round-2 evaluation was already running but before its output was read.

| # | Prediction | Result |
|---|---|---|
| P2.1 | NumPy inference reproduces the scikit-learn heads to within 1e-9 | **Hit**: max abs diff 8.9e-14 (and enforced by a test) |
| P2.2 | Headline dev metrics identical to round 1 within ±0.3 points (same model, same retrieval) | **Hit**: identical (64.5% resolved, 98.2% precision, 67.4% forced top-1); median latency under evaluation 6.0 ms |
| P2.3 | Median latency ≤ 8 ms; p99 ≤ 25 ms; single-core ≥ 120 queries/s | **Hit**: p50 5.7 ms, p99 16.1 ms, 165 q/s (`tahdeed bench`, 1,500 queries) |
| P2.4 | Resident memory ≤ 600 MB, load time ≤ 10 s | **Mixed**: RSS 486 MB (hit), load **18.8 s (miss)**: provenance hashing and the ambiguity tables added load cost. Tracked as E11. |
| P2.5 | Hypothesis fuzzing (300 + 120 examples) and pathological inputs never raise and stay < 2 s | **Hit**: 64 tests pass |
| P2.6 | Dashboard loads and resolves with all external hosts blocked except the tile server | **Hit**: only `tile.openstreetmap.org` was requested; page and result render |

## Round 3 (after TII review): generator gap, ablations, baselines

Written before `tahdeed studies` was run.

| # | Prediction | Result |
|---|---|---|
| P3.1 | v2 (from-Arabic) queries are harder than v1: forced top-1 ≤50 m at least 10 points lower | **Hit**: forced top-1 ≤50 m falls 66.0% → 49.8% (−16.2 points) on v2 |
| P3.2 | Even on v2, precision of *resolved* answers stays ≥ 90% (calibration should transfer even when accuracy does not) | **Hit**: resolved precision 97.0% on v2 (98.1% on v1). Calibration transfers; accuracy does not |
| P3.3 | Arabizi (digit) style is the hardest of the three v2 styles | **Hit**: Arabizi top-1 22.7% (precision of its confident answers 89.7%); gulf 57.8%, formal 60.5% |
| P3.4 | Removing consonant-class matching costs more on v2 than on v1 (so the mixed-benchmark loss is ≥ 3 points) | **Miss**: removing consonant-class matching changes top-1 by +0.02 points (CI −0.08..+0.10). It does nothing measurable on this benchmark |
| P3.5 | Removing isotonic calibration leaves forced top-1 unchanged but raises ECE by at least 3× | **Miss**: removing isotonic calibration leaves top-1 unchanged (−0.12, CI −0.24..0.00) but ECE is *lower* without it (0.007 vs 0.012). The raw boosted trees are already calibrated; isotonic adds step noise |
| P3.6 | Training without hole examples lowers mixed-benchmark resolved precision by ≥ 3 points | **Partial**: top-1 −4.1 points (significant), ECE 0.012 → 0.050, wrong confident answers 148 → 164; resolved precision only −1.3 points (predicted ≥3) |
| P3.7 | Char-trigram TF-IDF baseline lands ≥ 15 points below the full system on top-1 ≤50 m | **Near miss**: TF-IDF baseline is 13.3 points below (CI −15.0..−11.5), predicted ≥15 |
| P3.8 | At least one of the "recall aids" (siblings, fuzzy full-name, DP selection) does **not** produce a statistically significant gain on its own | **Hit**: sibling keys +0.5 (ns), consonant-class 0.0 (ns), all three recall aids together −0.36 (ns); fuzzy full-name −0.8 and DP selection −1.8 are significant but small |

## Round 4 (after ATRC review): Arabic-specific matching

Written before the Round 4 model was trained or evaluated. Round 3 baselines: v2 forced top-1 ≤50 m
49.8% (arabizi 22.7%, gulf 57.8%, formal 60.5%); v2 resolved precision 97.0%.

| # | Prediction | Result |
|---|---|---|
| P4.1 | Arabizi top-1 ≤50 m on v2 rises from 22.7% to at least 40% (digit decoding is the single largest known defect) | **Hit**: 48.8% |
| P4.2 | Formal and gulf styles each gain 3 points or less (their errors are not digit-related) | **Miss**: formal 60.5% → 65.7% (+5.2), gulf 57.8% → 64.6% (+6.8). The article, city-alias and span fixes helped every style |
| P4.3 | v1 headline (resolved precision) stays within ±0.5 points of 98.2%; resolved share within ±2 points | **Partial**: precision 98.5% (hit); resolved share 64.5% → 67.2% (+2.7, outside the band, in the good direction) |
| P4.4 | Landmark tier: "near X, city" within 200 m of the landmark at least 15 points higher with the tier on than off | **Hit, but only after a fix**: the first run showed 0% on and off. The ranker had never seen relation queries, and a trailing city name swallowed the landmark span. After fixing both: 75.3% with the tier, 0.1% without. Truth here is the landmark's own point, so this tests finding the landmark, not the offset a real "near" implies |
| P4.5 | Hand-written gold set (40 queries): top-1 ≤500 m at least 70%, but ≤50 m below 60% (human phrasing is harder than either generator) | **Half**: ≤500 m 77.5% (hit); ≤50 m 75.0% (miss: I expected human phrasing to be harder). 3 of 33 resolved answers are wrong, two by more than 100 km (a common street name matched in the wrong city) |
| P4.6 | Resolved precision on v2 stays ≥ 96.5% (calibration should keep transferring) | **Hit**: 97.6% |

## Final round: sealed split (10% of districts, never used for any decision)

Written before the final model was trained and before any sealed query was run. Dev reference
values are from the Round 4 model; the final model adds an interior-street-type span guard and
faster loading, so small movements are expected.

| # | Prediction | Result |
|---|---|---|
| F1 | Held-out benchmark on sealed: resolved precision within ±1.5 points of dev (98.5%); top-1 ≤50 m within ±4 points of dev (70.1%) | **Half**: precision 98.7% (hit). Top-1 68.3% on sealed vs 72.7% on dev with the final model: 4.4 points apart, narrowly outside the band. Sealed holds only 10% of districts, so more variance is expected |
| F2 | v2 (from-Arabic) forced top-1 ≤50 m on sealed between 55% and 66%; resolved precision ≥ 96% | **Hit** (on the edge): 66.0%; precision 97.2% |
| F3 | Hole benchmark on sealed: precision of resolved between 80% and 90% | **Hit**: 86.6% |
| F4 | ECE of P(≤50 m) at most 0.04 on every sealed benchmark | **Miss**: 0.030 (Abu Dhabi), 0.039 (holes), **0.054 (Dubai/Sharjah/Ajman POI)**. The POI benchmark's truth is weaker (POI points, not surveyed addresses) |
| F5 | Landmark queries on sealed: within 200 m at least 65% | **Hit**: 75.8% (0.0% with the tier off) |
| F6 | Load time ≤ 10 s; median latency ≤ 9 ms | **Hit**: load 8.0 s (was 18.8 s), median 5.8 ms, p99 17.5 ms, 156 q/s single core, RSS 490 MB |
| F7 | Final model's dev numbers show no regression greater than 1 point on any Round 4 headline (interior-type guard is not a net loss) | **Near miss**: everything improved (held-out resolved 67.2% → 69.4%, top-1 70.1% → 72.7%, v2 top-1 61.0% → 64.4%, Arabizi 48.8% → 51.3%) except landmark top-1 within 200 m, 75.3% → 74.2% (−1.1) |

# Phase 2 (branch `phase2-crosscity-bench`)

## Goal 1: cross-city confident-wrong answers

Written and committed **before any query of the cross-city set was run**. The set
(`src/tahdeed/crosscity.py`) is synthetic, rendered from OSM records, paired across evidence levels
(E0 street only, E1 + district, E2 + city). Dev split is used to choose the gate margin; the sealed
split is run once for the chosen margin. "Confident" means status `resolved`. Metrics: coverage
(share resolved), confident-wrong-city rate (wrong city among resolved), wrong-city-of-all
(resolved and wrong city, over all queries). All with Wilson 95% intervals.

| # | Prediction | Result |
|---|---|---|
| C1 | Before the gate (v2.0 behaviour), named streets at E0: confident-wrong-city rate among resolved is at least 10% | _pending_ |
| C2 | Numbered streets at E0 ("Street 5") have a confident-wrong-city rate at least twice that of named streets at E0 | _pending_ |
| C3 | E2 (city given) control: confident-wrong-city rate at most 2% for named streets | _pending_ |
| C4 | A city-evidence gate (abstain and ask which city when a rival in another city scores at least `margin` × the top) at the best margin cuts named-street E0 confident-wrong-city by at least 60% relative | _pending_ |
| C5 | The same gate costs at least 20% of E0 coverage (relative) on named streets: the cut is not free | _pending_ |
| C6 | E2 control outcomes change by no more than 0.5 points of coverage under the gate | _pending_ |
| C7 | Standard held-out dev benchmark: resolved share drops by at most 2 points and resolved precision moves by at most ±0.3 points | _pending_ |
| C8 | Candidate diversification alone (gate off) moves the standard held-out headline by at most 0.5 points | _pending_ |
| C9 | The margin chosen on dev transfers to sealed: the wrong-city-rate difference between dev and sealed is inside the combined interval | _pending_ |
| C10 | POI chain names at E0 (no city): the gate lowers confident-wrong-city by a smaller relative amount than for streets (POIs often have several instances in one city, so the ambiguity is not only about city) | _pending_ |
