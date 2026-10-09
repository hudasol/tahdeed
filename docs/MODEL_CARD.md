# Model card: tahdeed ranker

**What it is.** Four gradient-boosted tree ensembles (scikit-learn `HistGradientBoostingClassifier`, 250 trees, 31 leaves) each followed by isotonic regression, exported to plain arrays (`data/models/ranker.npz`) and run with NumPy. Inputs are ~57 numeric features describing *one candidate location for one query* (how well each name matched, how ambiguous the name is, whether the candidate's district and city agree with what the text says, how many rivals exist, ...). Outputs per candidate:

| Head | Meaning |
|---|---|
| `p50` | P(candidate within 50 m of the true location); only for tiers that claim a point |
| `p200`, `p1k` | P(within 200 m / 1 km) |
| `valid` | P(candidate is right *at its own tier*): right building, right street and city, right area, right city |

A fixed policy then chooses `resolved` (calibrated `p50` ≥ τ and no close rival), `approximate` (best trusted coarse candidate with an empirical radius), `ambiguous`, or `unresolved`.

**Intended use.** Turning free-text UAE addresses (Arabic, English, mixed) into coordinates *with an honest confidence*, for logistics triage, form validation, and as a candidate generator in front of a human or an official registry.

**Not intended for.** Anything that needs a guarantee about a specific address (emergency dispatch, legal notices), non-UAE addresses, or replacing Makani / Onwani / the National Address.

**Training data.** Synthetic queries rendered from OpenStreetMap address points in *train* districts (50% of districts by hash), noise model v1 (`noise.py`), 30% of queries with the true address hidden from the index so the model learns what absence looks like. Calibrated on a disjoint 20% of districts. Evaluated on `dev` (20%); a further 10% (`sealed`) is reserved for the final report.

**Performance** (dev split, synthetic queries): see `docs/EVALUATION.md`, `docs/studies.json`. Headline: resolved precision ≈98% at ≈64% resolved share with 0% holes; ≈94% with a 30% hole mix; on independently generated v2 queries (from Arabic names) resolved precision ≈97% but always-answer accuracy falls from 66% to 50%.

**Known limitations**
- Trained only on noise we simulated. Real query distributions will differ.
- Arabizi (digit) spellings are poorly handled (≈23% top-1 on v2).
- Dubai has almost no structured OSM addresses: the model has effectively never seen Dubai-style structured addresses and only Dubai *POI* queries are evaluated.
- The hole prior (30%) is an assumption; the calibration curve holds across 0-100% holes but precision does not (`docs/PREDICTIONS.md`).
- Isotonic calibration did not improve calibration over raw boosted probabilities in the ablation (ECE 0.012 vs 0.007).

**Ethical / privacy notes.** The model sees text, not people. Addresses are personal data: the API logs only a hash of the query unless `TAHDEED_LOG_RAW=1`. The gazetteer comes from public OSM data and contains buildings and POIs, not residents.

**Provenance.** The artefact manifest records the feature list, training configuration, array checksum and the SHA-256 of the gazetteer it was trained on. `tahdeed verify` checks all four.
