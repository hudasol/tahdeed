# Methodology

## 1. Problem
Given free text *t* written in Arabic, English or both, return (a) a point or a region *ĝ*, (b) a
calibrated probability that *ĝ* is within *r* metres of the intended location for r ∈ {50, 200, 1000},
and (c) an *action*: accept, accept as approximate, ask the user for a specific missing field, or
abstain. The target is not accuracy alone but **accuracy that the system can state in advance**.

## 2. Pipeline

1. **Normalise.** Unicode NFKC, diacritics and tatweel removed; alef/ya/ta-marbuta variants unified;
   Arabic-Indic and Persian digits mapped to ASCII; punctuation and bidi controls stripped.
2. **Skeleton keys.** Each name becomes a consonant skeleton shared by both scripts, e.g.
   `Jumeirah` and `جميرا` → `jmr`. Digraphs (kh, sh, gh, th, dh) map to single symbols; the Arabic
   definite article and Latin `Al/El` are stripped; Latin construct-state `-at` is repaired. A
   second, order-insensitive key handles "Khalifa City" / "مدينة خليفة". A third, *coarse* key merges
   consonant classes (j/g/k/kh/gh/y, s/z/sh, d/t, p→b, v→f) as a fallback.
   *Intrinsic check*: for 9,795 real (Arabic, English) street-name pairs in the Abu Dhabi import,
   skeleton equality rose from 89.2% to 97.7% after the fixes above.
3. **Parse.** House numbers (with keyword, position relative to a street-type word), units, Makani,
   postcodes, PO boxes (flagged as non-physical), landmark relations ("near", "opposite", `بجانب`).
4. **Match names.** All n-grams (≤8 tokens) are looked up against street, area, POI and city indices:
   exact skeleton, consonant-class siblings, and edit-distance (RapidFuzz) for long names. The
   non-overlapping span set that maximises a superadditive explained-mass score is chosen by dynamic
   programming (weighted interval scheduling).
5. **Generate candidates at eight tiers:** address, POI, interpolated, landmark, street+area,
   street, area, city. Interpolation places a missing number between its neighbours on the same
   parity side of the same street *within one district*. Candidate-level features record how it was
   found (`key_exact`, `area_match`, `city_match`, match view, key ambiguity, rivals).
6. **Score** with four boosted-tree heads; isotonic maps are fitted on held-out districts.
7. **Decide** with a fixed policy: τ is the smallest threshold with ≥95% precision on the calibration
   split; a runner-up more than 100 m away with ≥50% of the leader's score makes the answer
   *ambiguous*; coarse answers carry the empirical 90th-percentile radius of correct matches.

## 3. Evaluation design
- **Query generation.** v1 perturbs the English names (dropped fields, transliteration variants,
  typos, abbreviations, digits, reorderings); v2 romanises the *Arabic* names in three styles. v2
  shares no code or tables with v1 or with the matcher.
- **Splits** by district hash (train/calib/dev/sealed). No district crosses splits.
- **Holes.** For a fraction of queries the true address is removed from the index at query time.
- **Metrics.** Resolved share and precision, forced top-1 ≤ 50/200/1000 m, ECE, reliability,
  risk-coverage, latency; all with bootstrap intervals; comparisons are paired.
- **Predictions** are written before each run (`docs/PREDICTIONS.md`), including the misses.

## 4. What the evidence supports, and what it does not
Supported (dev split, 95% intervals in the JSON files):
- Calibration of the point probability holds across hole rates 0-100% and across both generators
  (ECE ≤ 0.05). This is the most defensible claim.
- Precision of confident answers is ≈98% (no holes), ≈94% (30% holes), ≈97% on v2.
- Interpolation (+8.5 points forced top-1), the ranker itself (+27 over hand-set rules), hole-aware
  training (+4 points, ECE 0.050 → 0.012), and DP span selection (+1.8) are real, measured gains.

Not supported:
- That consonant-class matching, sibling keys or full-name fuzzy spans earn their complexity: on
  the mixed benchmark their combined effect is −0.4 points (CI −1.0..+0.3). They are kept for now
  because the mechanism is sound and the benchmark may not exercise it (development round 4 revisits this).
- That isotonic calibration improves calibration (raw boosted probabilities are at least as good).
- Anything about real users. Both generators are ours.
- Any claim about Dubai addresses.
