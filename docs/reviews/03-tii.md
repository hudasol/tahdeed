# Review 3: TII (scientific rigour lens)

*Reviewer's stance: "What is the claim, what would falsify it, and did you try? Show me the
ablation, the baseline you did not design to lose, and a test set you did not write the system
against."*

## What is good

- Pre-stated evaluation design, district-level splits, sealed split now exists.
- Calibration reported with ECE and reliability, hole-rate sensitivity quantified.
- Honest failure analysis; predictions file records misses.

## Critique

**C1. One generator, one author.** Every number so far is on queries produced by `noise.py`, written by
the same person who wrote the matcher. The matcher's coarse consonant classes were designed against
the generator's consonant table. The reported 98% is a statement about *our* noise. The generator
perturbs the *English* OSM names; real users produce Latin text from the *Arabic* name, via a
different process (romanisation schemes, dialect pronunciation, Arabizi digits). That process is
not tested at all.

**C2. No ablations.** The system has eight claimed contributions (skeleton keys, consonant-class
siblings, fuzzy full-name spans, DP span selection, interpolation, landmark tier, calibration,
hole-aware training). Which of them earn their complexity? Unknown.

**C3. Weak baselines.** The naive fuzzy baseline is pre-filtered by house number (generous but
crude). There is no character-n-gram retrieval baseline, which is what a competent engineer would
build in an afternoon, and no "same ranker, no calibration" control.

**C4. No uncertainty on comparisons.** Intervals exist on headlines but differences between
systems are quoted without a paired test. A 1.5-point difference on 1,000 queries may be noise.

**C5. Reproducibility is manual.** There is no single command that rebuilds the gazetteer, retrains,
re-evaluates and regenerates every table, and no environment record in the result files.

**C6. Documentation is a README, not a scientific record.** No model card, no datasheet for the
gazetteer, no methodology write-up with the assumptions in one place, no figures.

**C7. Calibration is claimed but never shown.** ECE is a single number; the reliability and
risk-coverage curves exist only as JSON.

## Checklist (✅ done this round)

- [x] **T1** Independent generator **v2**: Latin text produced from the *Arabic* names via three romanisation styles (formal, Gulf-informal, Arabizi with digits), never touching the English names or v1's tables.
- [x] **T2** Inference-time ablations with a `Flags` object (coarse keys, sibling keys, full-name fuzzy, DP selection vs greedy, interpolation, landmarks, calibration, hole-aware ranker) with **paired bootstrap** differences.
- [x] **T3** Stronger baselines: character-trigram TF-IDF nearest neighbour over address strings (no house-number help), and "same candidates, raw uncalibrated GBM score".
- [x] **T4** `tahdeed reproduce`: build → train → eval → figures → tables, fixed seeds, environment record in every results file.
- [x] **T5** Figures: reliability diagram, risk-coverage curve, hole-sensitivity curve, generator-gap chart.
- [x] **T6** `MODEL_CARD.md`, `DATA_CARD.md`, `docs/METHODOLOGY.md`.
- [ ] **T7** Learned Arabic↔Latin matching (vs. rule keys). ➡ Round 4 (ATRC), where Arabic specifics are the topic.

## Result of this round (`docs/studies.json`, `docs/PREDICTIONS.md`)

| Question | Finding |
|---|---|
| Does it hold on queries we did not write? | Accuracy: **no**. Always-answer top-1 ≤50 m falls from 66.0% (v1) to 49.8% (v2). Calibration: **yes**. Precision of confident answers 98.1% → 97.0%. Arabizi is the hard case (22.7% top-1). |
| Which components earn their keep? | Ranker (+27.2 pts over hand-set confidence), interpolation (+8.5), hole-aware training (+4.1 and ECE 0.050 → 0.012), DP selection (+1.8), fuzzy full-name (+0.8). |
| Which do not? | Consonant-class matching, sibling keys: no measurable effect (CI spans 0). All three recall aids removed: −0.4 pts, not significant. |
| Is isotonic calibration useful? | No evidence. ECE without it 0.007 vs 0.012 with it. |
| Strong baseline? | Char 3-4-gram TF-IDF nearest neighbour: 37.9% vs 51.2% top-1 on the mixed benchmark (−13.3 pts, CI −15.0..−11.5). |

Eight predictions: five hit, one partial, two near-misses or misses worth reading (P3.4, P3.5).
The honest conclusion is uncomfortable and useful: **the recall machinery built in Round 1 to fix
consonant variants does not move the benchmark; the real transliteration problem is elsewhere**
(digits as letters, vowel-letters that become consonants, dialect substitutions). That is the brief
for Round 4.
