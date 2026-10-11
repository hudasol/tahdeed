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

**Performance**: see `docs/EVALUATION.md` (generated from the result files).

<!-- RESULTS:model_card BEGIN -->
Standard benchmark, sealed (run once): 61.0% answered, 99.0% of those within 50 m. Cross-city risk queries with no city given: wrong-city answers 12.0% (10.2-14.1) without the gate, 2.8% (2.0-4.0) with it. True address missing (dev): 87.9% of confident answers right. Dubai/Sharjah/Ajman POI calibration (dev) ECE 0.105 (was 0.069 on v2.0: a regression, see EVALUATION.md).
<!-- RESULTS:model_card END -->

**Training data.** Also includes landmark-relative queries ("near X, city"); without them the landmark tier answered nothing (found in Round 4).

**Known limitations**
- Trained only on noise we simulated. Real query distributions will differ.
- Arabizi spellings: about 50% top-1 on the independent generator (was 23% before digit decoding).
- Dubai has almost no structured OSM addresses; only Dubai *POI* queries are evaluated, and calibration there is weaker (ECE 0.05).
- The hole prior (30%) is an assumption; calibration holds across 0-100% holes but precision does not.
- Isotonic calibration shows no significant effect on top-1 and no ECE advantage over raw boosted probabilities; it is kept because it is harmless, not because it helps.
- A common street name present in several cities, written without the city, can still produce a confident answer in the wrong city when the true record is missing from the registry; the city gate reduces but does not remove this and costs coverage. Features `name_n_cities` and `city_share` and cross-city training queries were added in v2.1.

**Ethical / privacy notes.** The model sees text, not people. Addresses are personal data: the API logs only a hash of the query unless `TAHDEED_LOG_RAW=1`. The gazetteer comes from public OSM data and contains buildings and POIs, not residents.

**Provenance.** The artefact manifest records the feature list, training configuration, array checksum and the SHA-256 of the gazetteer it was trained on. `tahdeed verify` checks all four.
