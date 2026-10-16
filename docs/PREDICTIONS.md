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
| C1 | Before the gate (v2.0 behaviour), named streets at E0: confident-wrong-city rate among resolved is at least 10% | **Miss**: 0.0% (Wilson 95% CI 0-1%), 48% of queries resolved |
| C2 | Numbered streets at E0 ("Street 5") have a confident-wrong-city rate at least twice that of named streets at E0 | **Miss**: 0.0% (CI 0-3%) vs 0.0%: nothing to compare |
| C3 | E2 (city given) control: confident-wrong-city rate at most 2% for named streets | **Hit**: 0.0% (CI 0-1%) |
| C4 | A city-evidence gate (abstain and ask which city when a rival in another city scores at least `margin` × the top) at the best margin cuts named-street E0 confident-wrong-city by at least 60% relative | **Untestable**: baseline rate was already 0 |
| C5 | The same gate costs at least 20% of E0 coverage (relative) on named streets: the cut is not free | **Miss**: the gate changed named-street E0 coverage by under 1 point at every margin down to 0.05 (it fired on 1% of queries at 0.05) |
| C6 | E2 control outcomes change by no more than 0.5 points of coverage under the gate | **Hit**: unchanged |
| C7 | Standard held-out dev benchmark: resolved share drops by at most 2 points and resolved precision moves by at most ±0.3 points | **Hit** (trivially): 69.7% / 98.7% at margins 0.9-0.1; 69.2% / 98.8% at 0.05 |
| C8 | Candidate diversification alone (gate off) moves the standard held-out headline by at most 0.5 points | **Hit**: identical to baseline |
| C9 | The margin chosen on dev transfers to sealed: the wrong-city-rate difference between dev and sealed is inside the combined interval | **Not run**: no margin was worth choosing on this set |
| C10 | POI chain names at E0 (no city): the gate lowers confident-wrong-city by a smaller relative amount than for streets (POIs often have several instances in one city, so the ambiguity is not only about city) | **Untestable**: POI E0 resolved only 2% of the time, 0 wrong |

**What this first run (set v1, `docs/crosscity_v1_dev.json`) actually showed.** On queries whose street
*name* exists in several cities, the v2.0 system already made no confident wrong-city answers (0%,
upper bound 1%). Reason found by reading the set, not by tuning: a house number almost always
identifies one city, because the same (street, number) pair rarely exists in two cities. My set did
not exercise the real failure. The real exposures are (a) the same (street, number) in two cities
(collision), and (b) the true address missing from the registry while another city has that
(street, number) (hole with rival). The gold-set failure ("6 شارع الديرة الطوية" answered in Abu Dhabi
instead of Al Ain) is neither: it is a fuzzy span matching a different street. It is kept as a
regression case. Set v2 below is therefore designed **after** seeing v1's result; v1 stays in the
record as a null result.

### Goal 1, set v2: collisions and registry holes with a rival city

Written and committed before any v2 query is run. Strata: `*_collision` (the same street and number
exist in at least two cities, truth present), `*_hole` (truth hidden from the index, another city has
the same street and number), `named_unique` (control: number exists in one city only), `poi` and
`poi_hole` (same name in several cities). Evidence levels E0/E1/E2 as before. "Risk cells" =
collision + hole strata at E0.

| # | Prediction | Result |
|---|---|---|
| D1 | Baseline (v2.0 behaviour): confident-wrong-city among resolved in the risk cells at E0 is at least 15% | **Hit, far past it**: 97.6% (Wilson 95-99%) of the 15.1% of risk queries that were resolved were in the wrong city; that is 14.7% of all risk queries (n=1,646, dev) |
| D2 | Hole strata have a higher confident-wrong-city rate than collision strata at E0 (a hidden truth leaves only the rival to answer) | **Hit**: named holes 98.4% (27% resolved) vs named collisions 33% (1% resolved, n=6 resolved: wide interval). The system already abstains on collisions; the exposure is holes |
| D3 | Control (`named_unique`, E0) confident-wrong-city is at most 1% | **Hit**: 0.3% (CI 0-2%), 76.4% resolved |
| D4 | E2 (city given) confident-wrong-city in the risk strata is at most 3% | **Hit**: 1.6% (CI 1-3%) |
| D5 | There is a gate margin that cuts risk-cell E0 confident-wrong-city by at least 50% relative while losing at most 25% of risk-cell E0 coverage (relative) | **Miss**: the rate among resolved barely moves (97.6% → 95-96%) because the gate removes correct and wrong answers alike; in absolute exposure (wrong-city-of-all) margin 0.5 cuts 14.7% → 7.6% (-48%) at -48% coverage, margin 0.25 cuts to 6.0% (-59%) at -58% coverage. It never goes below 5.4%: those rivals are invisible |
| D6 | The same margin changes the control stratum (`named_unique`) E0 coverage by at most 3 points | **Miss, badly**: 76.4% → 33.3% at margin 0.5, 15.6% at 0.25. An exact hit whose record is present is indistinguishable from one whose record is missing |
| D7 | The same margin changes standard held-out dev coverage by at most 1.5 points and precision by at most ±0.3 | **Miss**: 69.7% → 65.5% resolved at margin 0.5 (62.1% at 0.25, 51.8% at 0.02); precision 98.7% → 98.8-99.1% |
| D8 | Diversification alone (gate off) changes the standard held-out headline by at most 0.5 points | **Hit**: identical to baseline on every cell |
| D9 | At the margin chosen on dev, the sealed risk-cell wrong-city rate is not significantly different from dev (intervals overlap) | **Hit** (sealed run once, after the final model): risk-cell wrong-city-of-all 2.8% (CI 2.0-4.0%) vs dev 3.0% (2.3-3.9%); baseline 12.0% (10.2-14.1%); standard-benchmark coverage 64.7%→61.0% (−3.6 pts), precision 98.9%→99.0%. Sealed numbered strata remain tiny (n=3), so only the pooled risk cell is quoted. |
| D10 | Hole strata at E0 remain the hardest: even with the gate, confident-wrong-city in them stays above 3% (a gate cannot see a rival that scores low) | **Hit**: 75-98% at every margin down to 0.02 |

### Goal 1, round 2: the calibrated alternative to a heuristic gate

Written and committed **before the retrain**. First dev run of set v2 (recorded in the table above as the
D-results) showed the heuristic city gate trades coverage for exposure almost one for one, because an
exact hit whose true record is missing looks identical to one whose record is present. The principled fix
is to give the ranker the evidence and the training examples so that its calibrated probability falls
where the evidence is thin, and abstention then comes from the ordinary threshold `tau`. Changes:
two new candidate features (`name_n_cities`, the number of cities the street or POI name occurs in; and
`city_share`, the share of the name's instances in the candidate's city) and cross-city queries from the
*train* and *calibration* districts added to the training mix. Dev and sealed districts are untouched.

| # | Prediction (model retrained; gate **off** unless stated) | Result |
|---|---|---|
| E1 | Risk cells at E0: confident-wrong-city among resolved falls from 97.6% to at most 60% | **Miss**: 98.2% (CI 95-99%) of resolved risk-E0 answers are still wrong-city. The model learned to answer less (coverage 14.8%→10.3%) but not to answer *differently*: when it resolves, it is on holes. |
| E2 | Risk cells at E0: wrong-city-of-all falls by at least 50% relative to the v2.0 baseline | **Miss**: 14.7%→10.1% wrong-of-all, a 31% relative cut (target 50%). |
| E3 | Control `named_unique` at E0 keeps at least 45% coverage (baseline 76%); i.e. cheaper than heuristic gate at margin 0.5 (33%) for a similar exposure cut | **Hit**: 72.4% coverage (CI in JSON) vs 76.4% baseline. Caveat: the retrained model barely moved this control; the heuristic gate at 0.35 costs far more (30.9%). |
| E4 | Standard held-out dev benchmark: resolved share within ±2 points of 69.7%, precision within ±0.3 | **Partial**: coverage 69.2% (within ±2 of 69.7%) hit; precision 99.08% vs 98.71% is +0.37, outside the ±0.3 band (in the good direction), so strictly a miss. |
| E5 | E2 (city given) risk-stratum confident-wrong-city stays at most 2% and coverage within 1 point of baseline | **Miss**: confident-wrong-city 0.8% (hit) but coverage fell 26.1%→22.2% (−3.9 points; target ≤1). |
| E6 | Adding the heuristic gate at margin 0.35 on top of the retrained model reduces risk-cell wrong-city-of-all by at most 20% further (relative): the model has absorbed most of it | **Miss** (in the informative direction): the gate still cuts risk wrong-of-all 10.1%→3.0% (−70% relative). The model did NOT absorb the gate's job; the gate remains the main protection. |
| E7 | Hole strata at E0 still have more than 50% wrong-city among resolved: the registry does not contain the evidence | **Hit**: named holes at E0 are 99.1% wrong-city among resolved. Missing registry evidence cannot be recovered by a calibrator. |
| E8 | ECE of P(within 50 m) on risk cells at E0 (resolved-tier candidates) at most 0.10 | **Miss**: ECE 0.222 on risk-E0 (named holes 0.398). The cell is selected on a hidden variable (record missing), so per-cell ECE is expected to be large; the mixture cell `all/E0` has ECE 0.083 and the standard benchmark 0.037. |

## Phase 2, T1: Dubai POI calibration regression (v2.0 to v2.1)

Written and committed **before any model below was trained or scored**. Observation that prompted it
(dev, published files): Dubai/Sharjah/Ajman POI ECE of P(within 50 m) rose from 0.069 (v2.0) to 0.105
(v2.1) and the answered (resolved) share fell from 72.8% to 63.3%. The published reliability table
shows the v2.1 model *underconfident* in the middle: bins 0.3 to 0.9 hold 364 queries whose
accuracy is 68% to 98%, against 302 in v2.0. Four things changed between the two: the features
`name_n_cities` and `city_share`, the cross city training mix, diversification of candidates across
cities, and the city gate.

**Data snapshot changes here.** The OSM extract used for every published number (2026-10-09, sha256
`875a1a23...`) is no longer offered by the mirror, which keeps only the latest file. Everything in
this section is run on the 2026-10-15 extract (sha256 `a0d00fee...`), with every model retrained on
it, so comparisons inside this section are like for like. Published sealed numbers stay on the old
snapshot and are labelled as such.

**Hypothesis H1.** The ECE rise comes from the cross city training mix, specifically its `poi_hole`
stratum: a POI name present in several cities with the true POI hidden, at E0 and at E2. Those rows
label multi city chain names as wrong, so the model lowers P(within 50 m) for correct Dubai chain
POIs. The features alone carry little signal without those rows. The gate cannot move the top fine
candidate's p50, so it does not move ECE, but it does cut the answered share (more "ambiguous").

**Models** (dev split only; one training seed, 0, for each, as for every published model; intervals
are bootstrap or Wilson over queries and do not include training variance):

| Model | features `name_n_cities`, `city_share` | cross city mix | `poi_hole` rows |
|---|---|---|---|
| M21 | on | on | on (v2.1 as published) |
| M_nofeat (ablation a) | masked | on | on |
| M_nomix (ablation b) | on | off | off |
| M20 | masked | off | off (v2.0 training) |
| M_nopoihole (fix candidate) | on | on | **off** |

Resolver flags: `shipped` (diversification on, gate on), `gate_off` (ablation c), `v20_flags`
(diversification off, gate off). Δ = ECE(M21, shipped) minus ECE(M20, v20_flags). Driver:
`tahdeed ablate-poi`, output `docs/poi_ablation.json`.

| # | Prediction | Result |
|---|---|---|
| T1.1 | The regression reproduces on the new snapshot: M21 shipped has POI ECE at least 0.085 and answered share at most 68% | |
| T1.2 | M20 with v20_flags has POI ECE at most 0.080 and answered share at least 69% (v2.0 behaviour reproduces) | |
| T1.3 | Ablation (b), M_nomix shipped, recovers at least 60% of Δ | |
| T1.4 | Ablation (a), M_nofeat shipped, recovers at most 40% of Δ (features are not the main cause) | |
| T1.5 | Ablation (c), M21 gate_off vs shipped: ECE moves by at most 0.01, answered share rises by at least 3 points | |
| T1.6 | M21 v20_flags vs gate_off (diversification alone): ECE moves by at most 0.015 | |
| T1.7 | Fix candidate M_nopoihole shipped: POI ECE at most 0.080 and answered share at least 66%; cross city risk E0 wrong city, % of all (gate 0.35) at most 3.9% (the upper end of the published dev interval) and inside the Wilson interval of M21 on the new snapshot | |
| T1.8 | M_nopoihole standard benchmark (crosscity driver, n=3000, gate 0.35): resolved share within ±1.5 points of M21, precision at least 98.8% | |

**Adoption rule, fixed now.** Candidates in order: M_nopoihole, then M_nomix. Adopt the first whose
shipped POI ECE is at least 0.02 below M21's, whose risk E0 wrong city, % of all at gate 0.35 is at
most 3.9% and inside M21's Wilson interval, and whose standard benchmark precision is at least 98.8%.
If none qualifies, keep M21 and document the trade off. If time allows, M21 and the adopted model
are retrained with seeds 1 and 2; the conclusion stands only if the sign of the ECE difference holds
for every seed.

## Phase 2, T2: answering "Which city?"

Written and committed before the measurement below was run. The resolver, API (`city` field),
batch (`city` column), CLI (`--city`) and dashboard accept an optional city. It is applied as if
the user had written the city after the address (the form the ranker saw in training as evidence
level E2), and a confident answer outside the given city is downgraded to "ambiguous". Measurement
(`tahdeed clarify`, output `docs/clarify_dev.json`): the cross city dev set (same generator and seed
as `crosscity_dev`), the model chosen in T1, shipped flags. Take every E0 query that came back
"ambiguous" with a "Which city?" question; resolve it again with the true city as the hint.
Hole strata (truth hidden) are reported separately: there the right outcome is *not* to answer.

| # | Prediction | Result |
|---|---|---|
| T2.1 | Non hole strata, E0 queries asked "Which city?": with the true city supplied, at least 60% become resolved within 50 m (Wilson interval reported) | |
| T2.2 | Same queries: at most 2% become resolved but more than 50 m away | |
| T2.3 | Hole strata asked "Which city?": with the true city supplied, at most 5% become resolved (any resolved answer there is wrong) | |
| T2.4 | The hinted status equals the status of the same record written with the city in the text (E2) for at least 95% of the asked queries | |

## Phase 2, T6 (exploratory): last meter entrance proposals

Written and committed before the extraction or the evaluation was run. **Exploratory**: not part of
any headline claim. Question: given a resolved building point, can open map geometry alone propose
where a delivery robot or courier should stop? Labels: entrance nodes that OpenStreetMap
contributors mapped as vertices of a building outline (`entrance=*` or `door=*`), inside the Abu
Dhabi emirate bounding box. Labels are **OSM derived**, not surveyed and not drawn by me; the
selection rule is fixed in code. The query point is the outline's centroid, and the mapped
entrances are hidden from the proposers. Metric: distance from the proposal to the nearest mapped
entrance of that building, share within 10 m with a Wilson interval. Baselines: the centroid itself
(simple) and the point of the nearest road closest to the centroid (what a geocoder returns).

| # | Prediction | Result |
|---|---|---|
| T6.1 | At least 100 buildings carry a mapped entrance vertex (n is reported) | |
| T6.2 | The outline point nearest to the nearest road is within 10 m of a mapped entrance for at least 35% of buildings | |
| T6.3 | The centroid is within 10 m for at most 20% | |
| T6.4 | The outline proposal's median distance is at least 30% lower than the centroid's | |
| T6.5 | The nearest road point is within 10 m for at most 25% (a road is not a door) | |
