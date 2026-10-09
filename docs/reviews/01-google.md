# Review 1: Google (ML systems + evaluation lens)

*Reviewer's stance: "I would not ship a number I cannot defend under a shifted distribution, and I
would not trust a calibration curve I have only seen on the distribution it was fitted on."*

## What is good

- Calibration is a first-class output (isotonic on held-out districts, ECE reported).
- District-level splits stop street-name memorisation.
- Abstention exists and is measured (risk-coverage).
- The failure analysis in `EVALUATION.md` is unusually candid.

## Critique

**C1. The headline precision is a property of the test mix, not of the system.**
The 98.1% resolved precision is measured with 0% holes. Under a 15% training mix the ranker learned
"same street + same house number ⇒ right". Remove the truth and precision drops to 71%. A production
system does not get to choose its hole rate, so the honest artefact is a *curve over hole rate*, and
training must see the deployment mix. This is classic prior shift and it was ignored.

**C2. 223 of the 330 wrong confident answers had the right street name, the right number and the
wrong district**, sometimes 126 km away at p=0.96. The query *said* the district. The model had
`area_consistent`, but it was computed per street (does this street exist in the district?), not per
candidate (is *this address* in the district?). The feature that mattered did not exist.

**C3. Interpolated points are scored as precise.** A point interpolated between neighbours at 100-170 m
carried P(within 50 m) of 0.5-1.0. The head was not given enough negatives for the tier.

**C4. The radius is a lie of omission.** It is the 90th percentile of the error *given the place is
right*. A user reads "within 2.5 km" as a guarantee. A guarantee needs a calibrated tail probability.

**C5. Retrieval, not ranking, caps recall.** 95 of 120 failed consonant-variant queries found *a*
street span but chose the wrong one. Three mechanisms: keys under 4 characters are excluded from
the coarse and fuzzy indices (so `Al Fagr` never finds `Al Fajr`); a short exact partial span
("kalifa") blocks the fuzzy full-name span; and when an exact key exists for a *different* street
the consonant-class sibling is never considered. Greedy selection, short-key exclusion, and
single-view retrieval are three independent recall bugs.

**C6. The ranker cannot see how lossy a key is.** `db` is "Dubai", "Dibba", and "Al Doob". No
feature carries ambiguity of the key or which retrieval view (exact, consonant-class, edit distance)
produced the match.

**C7. Evaluation hygiene.** No sealed split, predictions not pre-registered, no confidence intervals,
and one query generator written by the same author as the matcher.

**C8. Latency and memory are unmeasured as a system property.** 5 ms median is fine, but the p99, the
load time (7 s) and 420 MB resident are not tracked, and `/resolve/batch` runs serially.

## Checklist (✅ done this round, ➡ deferred to the round named)

- [x] **G1** Split `test` into `dev` (iterate) and `sealed` (final only); write predictions *before* runs (`docs/PREDICTIONS.md`).
- [x] **G2** Retrieval: consonant-class sibling keys retained alongside exact keys; short (3-letter) keys allowed with a weak-evidence cap; fuzzy spans for all n-grams (long names), not just uncovered tokens.
- [x] **G3** Span selection by dynamic programming over *explained mass* (superadditive) instead of greedy.
- [x] **G4** Candidate-level features: `key_exact`, `area_match`, `city_match`, `street_alt`, `street_ambig`, `poi_ambig`, `area_ambig`.
- [x] **G5** Interpolation also offered when every exact-number hit is outside the named district.
- [x] **G6** Train and calibrate on a 30% hole mixture; report **hole sensitivity** (0/15/30/50/100%).
- [x] **G7** Calibrated tail heads: P(within 200 m), P(within 1 km), reported next to P(within 50 m).
- [x] **G8** Bootstrap 95% CIs on headline metrics.
- [ ] **G9** Independent second query generator (Arabic→Latin romanisation schemes, Arabizi). ➡ Round 3 (TII)
- [ ] **G10** Latency p99, load time, memory, parallel batch. ➡ Round 2 (Edge: needs the pickle-free model)
- [ ] **G11** Hand-written gold set of realistic queries. ➡ Round 4 (ATRC)

## Result of this round (dev split; full table in `docs/PREDICTIONS.md`)

| Metric | v1.0 | after round 1 |
|---|---|---|
| Resolved share / precision@50 m (no holes) | 61.9% / 98.1% | **64.5% / 98.2%** |
| Forced top-1 ≤50 m | 64.6% | **67.4%** (CI 66.2-68.6%) |
| Holes: precision of resolved | 71.0% | **83.7%** |
| Consonant-variant top-1 ≤50 m | 45% | 49.8% |
| ECE P(≤50 m) / P(≤200 m) / P(≤1 km) | 0.020 / n/a / n/a | 0.021 / 0.019 / 0.015 |
| Median / p95 latency | 5 ms / 7 ms | 8.7 ms / 15.3 ms |

Process notes (honest): the first retrain *regressed* resolved share from 62% to 36%. Causes found
by sampling failures, not by guessing: a house number written before a street-type word
("٧٠٩ شارع …") was being absorbed into the street-name span; bare numbers at span edges produced
junk keys ("30 ash" → `30s`); and `street madinat al riyad` outcompeted `al nadi street` because
Latin street types follow the name. Each got a targeted fix and a unit test. Three of seven
predictions missed or nearly missed; they stay in the file.

Carried forward: G9, G10, G11, plus **new** items found while fixing: P1.4 consonant variants still at
50%; abstention under holes is mild.
