# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The benchmark has its own versioning in
[`bench/CHANGELOG.md`](bench/CHANGELOG.md).

Measured effects of each change are in [`docs/DESIGN_NOTES.md`](docs/DESIGN_NOTES.md); the
experiments behind them are in [`docs/PREDICTIONS.md`](docs/PREDICTIONS.md).

## [Unreleased]

### Changed

- The model is found at `models/ranker.npz` next to the gazetteer, the layout `tahdeed fetch` writes.
- In strict mode the API loads the model at startup and stops if it is missing or mismatched.
- API: request ids are validated, error responses carry the security headers, batch CSV cells that
  start like formulas are prefixed, batches run in a thread pool, `/docs` is removed.
- Phone numbers typed with Arabic digits, dots or brackets are redacted.
- Optional `TAHDEED_AUDIT_KEY` turns the logged query hash into an HMAC.
- The dashboard calls results mapped addresses, shows the licence attribution and a notice that
  results are experimental, and reports rate limits and network failures.
- The README reports the real text results next to the public baselines.

## [2.1.0] - 2026-10-28

### Added

- City gate: when the same street or POI name exists in several cities and the query gives no city,
  the resolver asks "Which city?" instead of answering. The gate threshold was selected on the dev
  split. The answer can be passed back as `city` in the API, `--city` in the CLI, a `city` column in
  batch CSV files and buttons in the dashboard.
- Cross city training mix and city share features in the ranker.
- Gulf-AddressBench in `bench/`: versioned datasets (standard, hole, POI, landmark, cross city and a
  hand written set), a scorer (`tahdeed bench score`) with Wilson intervals, baseline predictions and
  a generated report, `docs/BENCH_REPORT.md`.
- Human written query collection kit in `bench/human_kit/` with consent text, instructions in English
  and Arabic, a protocol, an offline form and `tahdeed human` for ingestion and evaluation.
- Rate limiting on `/resolve` and `/resolve/batch` (token bucket per client, HTTP 429 with
  `Retry-After`), configured with `TAHDEED_RATE_LIMIT`.
- Docker image hardening (pinned dependencies, non root user, read only root filesystem, no
  capabilities) and a CI job that builds the image and smoke tests it.
- Exploratory `lastmeter` module that proposes entrance points from OpenStreetMap geometry.
- Documentation: deployment guide, open data source survey for Dubai addresses, and a note on the
  second sealed set.
- Continuous integration checks that benchmark results and generated documents reproduce from their
  scripts.
- Project files: contributing guide, security policy, code of conduct, issue and pull request
  templates, editor configuration, Makefile, pre-commit configuration, release workflow and release
  guide.
- Download helper `tahdeed.fetch.fetch_data` that fetches the gazetteer and model from a release and
  verifies their SHA-256 values against `MANIFEST.json` on the `data` branch.

### Changed

- Decision order: a fine candidate (POI or address) with p_valid of at least 0.40 is offered as the
  approximate answer ahead of a coarse city, and an approximate fine answer carries a radius taken
  from the calibrated heads instead of claiming 25 m.
- A POI whose Latin name shares only a consonant skeleton with a city word, or is not spelled
  recognisably like the span (similarity below 60), is no longer a match ("Sheikh Zayed Road Dubai"
  no longer returns a bank, "Dubai Airport" no longer returns "Dibba Airport" or "Euro Part").
- `tahdeed fetch` downloads the gazetteer and the ranker from the `data` branch and verifies them
  against `MANIFEST.json`.
- The dashboard now ships inside the package (`src/tahdeed/web`), so installed copies serve it.
- The audit log redacts contact details before hashing or logging query text.
- `docs/ROADMAP.md` and `docs/reviews/` were replaced by `docs/DESIGN_NOTES.md`.
- Package metadata completed (licence expression, classifiers, keywords, URLs, extras), and a mypy
  baseline was added to continuous integration.

### Fixed

- The audit logger now attaches a stdout handler under uvicorn, so audit lines are no longer dropped
  in containers.
- Worker processes no longer stall after forking, because the loaded gazetteer is frozen from the
  garbage collector first.

### Removed

- Committed logs, run markers and the original planning file.

## [2.0.0] - 2026-10-10

### Added

- Interior street type guard: a span that contains a street type word that is not at its edge is
  rejected, which removed one class of confident answers in the wrong city.
- Sealed split evaluation, run once, with predictions recorded beforehand.

### Changed

- Load time fell from about 19 s to 8 s by memoising the name to key generation.
- Both models were retrained on the final code and every document number was regenerated from the
  result files.
- The model card states that isotonic calibration is kept because it is harmless, not because it
  improves on raw probabilities.

## [1.5.0] - 2026-10-10

### Added

- Arabizi digit decoding inside words, romanised street type words, a wider set of Arabic and Latin
  articles, and city alias keys exempt from the minimum length filter.
- Landmark query generator and an on and off study of the landmark tier.
- Hand written set of 40 queries and the `tahdeed gold` command.
- PII guard that removes phone numbers, e-mail addresses and Emirates ID numbers before matching.
- `RegistryAdapter` protocol (interface only).

### Changed

- The ranker is trained on landmark relative queries. Before this the landmark tier answered nothing.

## [1.4.0] - 2026-10-10

### Added

- Independent query generator (v2) that produces Latin text from the Arabic names in three styles.
- Inference time ablations with paired bootstrap differences, a character n gram baseline and a raw
  score control.
- Figures for reliability, risk and coverage, hole sensitivity and the generator gap.
- Model card, data card and methodology document.

## [1.3.0] - 2026-10-10

### Added

- Pickle free model: the four heads are exported to `.npz` with an embedded manifest and run in
  NumPy. scikit-learn is needed only for training.
- Provenance checks between gazetteer, model and code, and `tahdeed verify`.
- Property based fuzzing, a per query time budget, a privacy preserving audit log and `degraded` and
  `calibrated` flags in responses.
- Security headers, request body limit and optional bearer token in the API.
- Dockerfile, pinned constraints, a Python 3.11 to 3.13 test matrix, coverage gate, `pip-audit`,
  multi process `batch` and `tahdeed bench`.

### Changed

- The dashboard no longer loads scripts or fonts from public hosts. The tile server is configurable.

## [1.2.0] - 2026-10-10

### Added

- Dev and sealed split of the held out districts, and bootstrap confidence intervals.
- Calibrated heads for P(within 200 m) and P(within 1 km).
- Candidate level features for exact key, area match, city match and key ambiguity.
- Training on a 30% hole mixture, and a hole sensitivity report.

### Changed

- Span selection uses dynamic programming over explained mass instead of a greedy choice.
- Consonant class sibling keys and fuzzy spans for all n grams improve retrieval recall.

## [1.1.0] - 2026-10-10

### Added

- Root cause analysis of the limits found in 1.0 and the plan for the following releases.

## [1.0.0] - 2026-10-09

### Added

- Normalisation of Arabic and Latin text, consonant skeleton keys shared by both scripts, and a query
  parser for house numbers, units, Makani codes, PO boxes and landmark phrases.
- Gazetteer build from an OpenStreetMap extract (`tahdeed build`).
- Resolver with exact, coarse and fuzzy span competition, candidates at several tiers, boosted tree
  scoring, isotonic calibration and an abstention policy (`tahdeed train`).
- Evaluation harness with synthetic query generation (`tahdeed eval`).
- Standard bilingual address form, FastAPI service with `POST /resolve`, `POST /resolve/batch` and
  `GET /health`, command line interface and a map dashboard.

[Unreleased]: https://github.com/hudasol/tahdeed/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/hudasol/tahdeed/releases/tag/v2.0.0
[1.0.0]: https://github.com/hudasol/tahdeed/releases/tag/v1.0.0
