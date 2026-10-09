# tahdeed — project plan

Working name: **tahdeed** (تحديد, "pinpointing"). Status: plan v1, written before any code.

## 1. Problem

The UAE has no single address a program can rely on.

- **Dubai** uses Makani: a 10-digit code per building entrance. It covers Dubai only.
- **Abu Dhabi** uses Onwani: building number + street + city, with address boards and QR codes on about 200,000 buildings. The Department of Municipalities and Transport reported completion of 87% in Abu Dhabi City, 79% in Al Ain and 99% in Al Dhafra (mid-2025 release).
- **Federal level:** the National Geospatial Feature Catalogue defines a National Address (Makani + postal code + special code) aggregated from the emirates by the Federal Geographic Information Center. It is a specification and a locator service, not an open layer a courier or an app can call.
- **People still write free text:** "Villa 14, near the Spinneys, Jumeira 3", "شارع الأسد بجانب المطعم", or a mix. UAE law requires place names in Arabic and English, so every place has at least two spellings, and Arabic-to-Latin transliteration adds more ("Jumeirah", "Jumeira", "Jumeirah").
- Logistics operators report that incomplete addresses and landmark-only locations are a leading cause of failed first deliveries. Those figures come from vendor blogs, so we treat them as motivation, not as evidence. Our own evaluation is the evidence.

The gap is not "another map". It is a **translation layer** between how people write addresses and the keys the official systems use, one that is honest about when it cannot tell.

## 2. What we build

A resolver that takes a free-text address (Arabic, English, or mixed) and returns:

1. ranked candidate locations (coordinates and an uncertainty radius),
2. a standardized, bilingual address (Onwani-style building / street / district / city / postcode where known),
3. a **calibrated confidence** (the probability that the top candidate is within a stated distance of the truth),
4. an **abstain / ask** decision with the specific missing field ("add a building number", "which Jumeira?"),
5. an explanation of which tokens matched which gazetteer fields.

It is shipped as a Python library, a CLI, a FastAPI service, a batch CSV mode, and a dashboard with a map.

### Non-goals

- Not a new map and not a routing engine.
- No claim to resolve official Makani or Onwani identifiers. Those registries are not open. We validate Makani format and provide an adapter interface.
- No LLM in the core path (no API keys, deterministic, reproducible, offline).

## 3. Data (verified in this environment)

Source: OpenStreetMap UAE extract (`download.openstreetmap.fr`, 88 MB, snapshot of 2026-10-09). Licence ODbL; code is MIT; the derived database is not committed in full, only a small attributed fixture.

Survey of the extract:

| Layer | Count | Notes |
|---|---|---|
| Address points with house number + street | ~130k nodes, ~22k ways | |
| ...of which Abu Dhabi / Al Ain / Al Dhafra | ~125k | structured: Arabic and English street, district, subdistrict, postcode |
| ...of which Dubai | a few hundred | Dubai addressing in OSM is mostly POI-attached and messy |
| Named streets (highways) | ~88k | many with `name:ar` and `name:en` |
| Bilingual named features | ~85k ways, ~4k nodes | |
| `place=` features (suburbs, neighbourhoods, towns, villages) | ~1.7k | |

Consequences, stated up front:

- **Abu Dhabi has real ground truth** (an Onwani-aligned structured import). It gives a proper benchmark.
- **Dubai does not.** It will be evaluated on a separate, explicitly weaker benchmark built from POI-attached addresses, and reported separately. We will not average the two.

## 4. Method

### 4.1 Normalization
- Arabic: strip diacritics and tatweel, unify alef/hamza, ya/alef-maqsura, ta-marbuta, convert Arabic-Indic and Persian digits.
- Latin: casefold, strip punctuation, expand/contract street-type abbreviations (st, rd, str, ave, blvd), normalize `Al/El/Ar/As/Ash/...` prefixes.
- Cross-script matching without a full transliterator: map both scripts into a **consonant skeleton** (Arabic letters to a coarse Latin class; Latin text to the same classes, vowels and doubled letters collapsed). "Jumeirah", "Jumeira" and "جميرا" land on the same skeleton key. Skeleton equality is a feature, not a decision.

### 4.2 Parsing
Rule-based extraction of: building/villa/unit number, street, district/community, city/emirate, postcode, Makani number (10 digits, optionally `12345 67890`), PO box (flagged as non-physical), and landmark relations (`near`, `opposite`, `behind`, `next to`, `بجانب`, `مقابل`, `خلف`).

### 4.3 Candidate generation (tiered)
Exact structured match → street + district → street → district / place → landmark / POI → city only. Each tier carries a different uncertainty radius.

### 4.4 Ranking and calibration
- Features per candidate: skeleton match, fuzzy score per field, tier, number match, district–street consistency, candidate-set margin, token coverage.
- A gradient-boosted model predicts `P(top-1 within 50 m)`; an isotonic calibrator is fit on a held-out split.
- Abstention is a threshold on calibrated confidence plus a structural rule (e.g. street found but no building number → ask).

### 4.5 Output standardization
Bilingual Onwani-style form. For Dubai: the matched POI/street/area plus a Makani format check.

## 5. Evaluation (pre-registered)

All numbers below will be produced by `tahdeed eval` and written to `docs/EVALUATION.md`. Predictions are written *before* the run, in the same file.

**Splits.** Gazetteer addresses are split by **district**, not at random: train the ranker/calibrator on some districts, test on unseen ones. This prevents the model from memorizing street names.

**Query generation (noise model).** From each address: drop fields; shuffle order; Arabic-only, English-only and mixed rendering; Arabic-Indic digits; transliteration variants; abbreviations; typos (edit, swap, drop, double); landmark-only variants from POIs; "building number unknown".

**Benchmarks**
1. *Abu Dhabi structured* (primary). Truth = the address point.
2. *Coverage hole.* 10% of address points are removed from the index; queries for them should **abstain or fall back to a coarser tier with an honest radius**, not hallucinate a precise point.
3. *Dubai POI* (secondary, weaker). Truth = the POI location; text = name + street + area.
4. *Small external baseline.* Nominatim on a sample of at most 200 queries (rate-limited, polite user agent). It uses the same OSM data, so this compares matching logic, not data.

**Metrics**
- Top-1 within 50 m / 200 m / 1 km, by tier and by noise type.
- Calibration: reliability curve and ECE.
- Selective prediction: accuracy vs coverage (risk–coverage) curve, precision of abstain/ask.
- Latency per query and throughput.

**Baselines:** naive fuzzy match (concatenate and `token_set_ratio`), per-field fuzzy without calibration, Nominatim sample.

**Honest failure reporting.** Failures and surprises are documented, not hidden: what broke, what was fixed, what remains.

## 6. Architecture

```
src/tahdeed/
  normalize.py      # scripts, digits, skeleton keys
  parse.py          # components, landmark relations, Makani/PO box
  gazetteer.py      # OSM build + load (SQLite) + indices
  resolve.py        # candidate generation, ranking, explanations
  calibrate.py      # features, model, isotonic, abstention policy
  standardize.py    # bilingual Onwani-style output, Makani check
  noise.py          # query noise generators
  evaluate.py       # benchmarks, metrics, report writer
  api.py            # FastAPI
  cli.py            # tahdeed resolve|batch|build|eval|serve
  web/              # dashboard (map, explanation view)
tests/
docs/
```

Dependencies kept small: Python 3.11+, rapidfuzz, numpy, scikit-learn, pyosmium (build only), FastAPI/uvicorn.

## 7. Milestones and tags

| Tag | Content |
|---|---|
| `v0.0.1-plan` | plan.md, README, licence, scaffolding |
| `v0.1.0-normalize` | normalization, skeleton keys, parser, tests |
| `v0.2.0-gazetteer` | OSM build pipeline, SQLite gazetteer, fixture |
| `v0.3.0-resolver` | tiered resolver, explanations, standardizer |
| `v0.4.0-calibration` | features, calibrated confidence, abstention |
| `v0.5.0-eval` | benchmarks, baselines, `docs/EVALUATION.md` |
| `v0.6.0-api` | FastAPI, CLI, batch mode |
| `v0.7.0-dashboard` | map UI with explanation view |
| `v1.0.0` | docs, limits, final evaluation, CI |

Commit small, keep tests green at each commit.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| OSM Dubai addresses are sparse | Separate weaker benchmark; the product's value there is the tiered fallback and honest abstention |
| Government registries close the gap | Position as the translation layer from free text to official keys; adapter interface for Makani / Onwani |
| Synthetic noise is not real user noise | State this plainly; include POI-derived and landmark queries; invite real data via the batch mode |
| Overclaiming accuracy | Evaluation reports by tier and district split; failures documented |
| Sandbox blocks tag pushes or repo-settings edits | Provide a script and exact manual steps |

## 9. Definition of done

- `pytest` green; `ruff` clean.
- `docs/EVALUATION.md` with pre-registered predictions and results, including failures.
- API, CLI and dashboard run from a fresh clone with one build command.
- README states what it does, what it does not, data licence, and limits.
