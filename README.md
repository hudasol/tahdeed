# tahdeed · تحديد

**Bilingual Arabic/English address resolver for the UAE.** It turns messy free-text addresses into coordinates, an Onwani-style standard form and a calibrated confidence score, and it abstains when an address is too ambiguous.

> **Status: v2.0.** Five review rounds (Google, Edge, TII, ATRC, senior) each produced a critique, a checklist and measured results: [`docs/ROADMAP.md`](docs/ROADMAP.md), [`docs/reviews/`](docs/reviews/). Predictions were written before each run: [`docs/PREDICTIONS.md`](docs/PREDICTIONS.md). Results: [`docs/EVALUATION.md`](docs/EVALUATION.md).

## The problem

The UAE has no single address a program can rely on. Dubai uses Makani (a 10-digit code per building entrance, Dubai only). Abu Dhabi uses Onwani (building number, street, city). The federal National Address is a specification that aggregates the emirates' systems, not an open layer an app can call. Meanwhile people write "Villa 14, near the Spinneys, Jumeira 3" or "شارع الأسد بجانب المطعم", and every place has several spellings because Arabic names are transliterated in many ways.

tahdeed is a **translation layer** between how people write addresses and the keys official systems use, and it is explicit about when it cannot tell.

## What it does

Given a free-text address (Arabic, English or mixed), it returns:

- ranked candidate locations with an uncertainty radius,
- a standardized bilingual address (building / street / district / city / postcode where known),
- a calibrated confidence: the probability that the top candidate is within a stated distance of the truth,
- an abstain / ask decision naming the missing field (for example "add a building number"),
- when the same name exists in several cities, the question "Which city?" with the candidate cities; passing the answer back as `city` (API, CLI `--city`, dashboard buttons) resolves the query,
- an explanation of which parts of your text matched which gazetteer fields.

It runs offline and deterministically. No LLM and no API keys are involved.

## What it does not do

- It is not a map or a routing engine.
- It cannot resolve official Makani or Onwani identifiers, because those registries are not open. It validates Makani format and exposes an adapter interface.
- Coverage depends on OpenStreetMap. Abu Dhabi emirate has structured, bilingual address data; **Dubai addressing in OSM is sparse**, so Dubai results are reported separately and are weaker.

## Data and licence

- Code: MIT (see `LICENSE`).
- Data: © OpenStreetMap contributors, ODbL 1.0. The full derived gazetteer is built locally by the build command and is not committed. A small attributed fixture is included for tests. See `data/NOTICE.md`.

## Results

Generated from the result files by `scripts/make_results_blocks.py`; nothing in this block is hand-written. Intervals are Wilson 95%.

<!-- RESULTS:results BEGIN -->
| | dev (model used to choose the gate) | sealed (run once) |
|---|---|---|
| Standard benchmark: answers it is confident about | 65.1% | 61.0% |
| ...of those, within 50 m | **99.2%** | **99.0%** |
| Forced top-1 within 50 m | 72.0% | 68.2% |
| ECE of P(within 50 m) | 0.037 | 0.025 |
| **Wrong-city answers, % of cross-city risk queries with no city given** (no city gate (v2.0 behaviour)) | 10.1% (8.7-11.6) | 12.0% (10.2-14.1) |
| **Wrong-city answers, % of cross-city risk queries with no city given** (city gate on (default)) | 3.0% (2.3-3.9) | 2.8% (2.0-4.0) |
| ...cost: answered share of those queries | 3.1% (2.4-4.1) | 3.0% (2.2-4.2) |
| ...cost: asked "which city?" on unique names (E0) | 41.6% | 37.8% |
| ...with the city written (E2), wrong-city rate of answers | 0.8% (0.3-2.4) | 0.4% (0.1-2.1) |
| True address missing from the index: precision of confident answers | 87.9% | not re-run |
| Dubai/Sharjah/Ajman POI queries: answered / ECE | 63.3% / 0.105 | not re-run |
| Latency (median, one core) | 6.2 ms | |

Cross-city rows use the synthetic `crosscity` set (pairs of the same record with and without district/city evidence; composition chosen to expose the failure, **not** a prevalence estimate). The standard-benchmark coverage without the gate was 64.7% on sealed. Frozen v2.0 release, sealed, for reference: 65.5% answered, 98.7% within 50 m.
<!-- RESULTS:results END -->

Caveats: queries are synthetic (plus 40 hand-written ones), truth is OpenStreetMap, Dubai is evaluated only on POI queries. The human-written set is **pending real data** (`bench/human_kit/`). Full tables, ablations, predictions with hits and misses ([`docs/PREDICTIONS.md`](docs/PREDICTIONS.md)) and every known failure: [`docs/EVALUATION.md`](docs/EVALUATION.md). Benchmark: [`bench/`](bench/README.md), report in [`docs/BENCH_REPORT.md`](docs/BENCH_REPORT.md).

## More

[`bench/`](bench/README.md) Gulf-AddressBench (datasets, split and contamination policy, scorer: `tahdeed bench score predictions.jsonl`) · [`bench/human_kit/`](bench/human_kit/README.md) human-written set collection kit (no data yet) · [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) open-data survey for Dubai addresses (nothing usable found) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) rate limiting, Docker, hosting limits. · [`docs/EDGE_PROPOSAL.md`](docs/EDGE_PROPOSAL.md) two page proposal note · [`docs/SEALED2.md`](docs/SEALED2.md) why no fresh sealed set exists yet · [`CITATION.cff`](CITATION.cff) how to cite the benchmark.

## Honest limits

- **Synthetic queries.** No query in any benchmark came from a real user. The largest open gap; only real logs close it.
- **OSM is not an official registry.** A missing record yields a confident wrong neighbour (see the missing-address row above). `RegistryAdapter` is an interface only and is not wired in.
- **Common street names across cities.** Without the city, a name present in several cities is answered or refused by a calibrated *city gate* (asks "which city?"). The gate cuts wrong-city answers on the risk set but cannot see a record that is missing from the registry, so some exposure remains; and it costs coverage. Numbers above; analysis in `docs/EVALUATION.md`.
- **Arabizi** is the weakest style (about 50%).
- **Landmark benchmark** tests finding the landmark, not the offset "near" implies.
- Does not resolve official Makani / Onwani / National Address codes. Dubai structured addresses are thin in OSM.
- The Docker image is built and smoke-tested in GitHub Actions (job `docker`), not in the development sandbox.

## Author

Huda Mueen.
