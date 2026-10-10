# Review 5: senior AI engineer, final review and polish plan

*Reviewer stance: someone who has to sign off before this is shown to people who will probe it.
Four rounds fixed what each reviewer found. This round asks what is still wrong, what is merely
unproven, and what must be done before calling it finished.*

## What is solid

- Evaluation hygiene: district-hash splits, predictions written before runs, paired bootstrap on every comparison, an independent generator, a hand-written set, and ablations that were allowed to say "no effect" (and did, twice).
- Calibration transfers across generators (ECE ≤ 0.03 on both) even where accuracy does not. This is the property a downstream user relies on.
- Operations: provenance checks that fall back to degraded mode instead of silently using a mismatched model, a time budget, request limits, fuzzed inputs, offline dashboard.

## Limitations that remain (ranked by how much they would hurt a user)

**L1. Confident wrong answers when a common street name exists in several cities.** The gold set
produced two answers over 100 km away at p≈0.7. In one, a coarse key merged a street word with the
neighbouring area word; in the other, a span crossed a street-type word into the area and city.
The second is fixed this round (interior street-type guard). The first (cross-token coarse merge)
is documented, not fixed.

**L2. Training and evaluation data are synthetic.** The generators are better than they were (v2 is
independent of the training generator, the gold set is human-written), but no query in any of them
came from a real user. The 40-row gold set has about ±13 points of sampling uncertainty. This is
the largest unclosed gap and only real query logs close it.

**L3. The registry is OpenStreetMap, not an official source.** A missing record is the dominant
error (hole benchmark: 85% precision of resolved answers when the true address is absent).
`RegistryAdapter` is an interface only; nothing is wired to it.

**L4. Landmark evaluation tests finding the landmark, not the offset.** "Near X" truth is X.
The shipped radius comes from a table of relation radii that is a judgement, not a measurement.

**L5. Interpolation is the biggest single contributor (+9.8 points) and the least verified.**
It assumes house numbers increase along a street. The ranker was trained on its own outcomes, but
no external check (surveyed addresses) exists.

**L6. Dockerfile has never been built** (no container runtime in the working environment). CI
covers tests and lint only.

**L7. Load time** was 19 s after the Round 1 index work; that is a startup cost, not a request cost,
but it matters for serverless deployment.

## Checklist (✅ done in this round)

- [x] **S1** Interior street-type guard: a span containing a street-type word that is not at its edge is rejected (fixes one of the two gold-set >100 km errors).
- [x] **S2** Load time: memoise name-to-key generation (the same street names recur across thousands of rows). 19 s → 8 s.
- [x] **S3** Retrain both models on the final code; re-run dev evaluation and confirm no regression against Round 4 (F7).
- [x] **S4** One sealed-split evaluation with predictions written first (F1–F6), reported whatever it shows.
- [x] **S5** Regenerate every doc number from `docs/eval.json`, `docs/studies.json`, `docs/gold.json`; regenerate figures; rewrite README "Honest limits" and `EVALUATION.md` from the final results.
- [x] **S6** Keep isotonic calibration (no longer significantly different from raw; harmless) but say so in the model card instead of claiming it helps.
- [ ] **S7** Fix the cross-token coarse merge (L1 case 1). Deferred: needs a feature for "span swallowed a token that matches an area exactly", i.e. another retrain cycle with its own evaluation; listed under future work.
- [ ] **S8** Wire `RegistryAdapter`, build and test the Docker image, add real-query evaluation. Cannot be done from this environment.

## Plan for the polished product

1. Apply S1/S2, retrain both models once. 2. Dev evaluation + studies + gold set, compare to Round 4.
3. Sealed evaluation once. 4. Regenerate docs and figures from the JSON, not by hand.
5. Version 2.0.0, tag locally, push main, list the manual steps.

## Result of this round

| | Round 4 (dev) | Final (dev) | Final (sealed, run once) |
|---|---|---|---|
| Held-out: resolved share / precision | 67.2% / 98.5% | 69.4% / 98.8% | 65.5% / 98.7% |
| Held-out: forced top-1 ≤50 m | 70.1% | 72.7% | 68.3% |
| v2 independent generator: forced top-1 | 61.0% | 64.4% | 66.0% |
| Arabizi (v2) | 48.8% | 51.3% | 53.7% |
| Landmark within 200 m | 75.3% | 74.2% | 75.8% |
| Hand-written gold set ≤50 m (n=40, partly tuned on) | 75.0% | 85.0% | - |
| Load time | ~19 s | 8 s | 8 s |

The interior street-type guard was a net gain everywhere except a 1-point dip on landmark queries.
Seven sealed predictions: four hit, one half, one near miss, **two real misses** (F1 top-1 gap
between dev and sealed; F4 POI calibration 0.054). Sealed is 10% of districts, so some spread
between splits is expected; the POI ECE is a genuine weakness of a benchmark with weaker truth.

S7 and S8 stay open and are listed under Honest limits in the README.
