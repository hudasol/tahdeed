# tahdeed · تحديد

tahdeed resolves free text UAE addresses, written in Arabic, English or a mix, to coordinates, a standard bilingual address form and a calibrated confidence. When an address is too ambiguous to answer reliably, it abstains and says which detail is missing.

The resolver runs offline and deterministically. It uses no language model and no API keys. Version 2.0.0; the change history is in [`CHANGELOG.md`](CHANGELOG.md).

## Installation

From source, with Python 3.11 or newer:

```bash
git clone https://github.com/hudasol/tahdeed.git
cd tahdeed
pip install -e .            # resolver and API
pip install -e ".[train]"   # adds scikit-learn, needed only to train a model
pip install -e ".[build]"   # adds osmium, needed only to build a gazetteer from an OSM extract
```

With Docker, the image contains the code and the dashboard but no data. The gazetteer and model are mounted at `/data`:

```bash
docker build -t tahdeed .
docker run --rm -p 8000:8000 --read-only --tmpfs /tmp --cap-drop ALL \
    --security-opt no-new-privileges -v "$PWD/data:/data:ro" tahdeed
```

The data directory must hold `gazetteer.sqlite` and `ranker.npz`. Build them yourself (below), or download them from a release with `tahdeed.fetch.fetch_data`, which checks SHA-256 values against `data/MANIFEST.json` (see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).

## Quick start

To build the full data from OpenStreetMap:

```bash
# Extract: https://download.openstreetmap.fr/extracts/asia/united_arab_emirates.osm.pbf
tahdeed build united_arab_emirates.osm.pbf   # about 30 s, writes data/gazetteer.sqlite
tahdeed train                                # about 5 min, writes data/models/ranker.npz
tahdeed resolve "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi"
tahdeed serve                                # API and dashboard at http://127.0.0.1:8000
```

To try the service without the full data, use the small fixture in the repository (an OpenStreetMap excerpt around Al Khalidiyah, Abu Dhabi) with a model trained on it. This model only exercises the service. Its confidence values say nothing about accuracy on real data.

```bash
pip install -e ".[train]"
python scripts/make_smoke_model.py /tmp/tahdeed-smoke
TAHDEED_DB=/tmp/tahdeed-smoke/gazetteer.sqlite TAHDEED_MODEL=/tmp/tahdeed-smoke/ranker.npz \
    tahdeed serve
```

A request and the response from that service (abridged):

```bash
curl -s -X POST http://127.0.0.1:8000/resolve -H 'Content-Type: application/json' \
    -d '{"address": "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi"}'
```

```json
{
  "query": "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi",
  "status": "resolved",
  "best": {
    "tier": "address",
    "lat": 24.469511,
    "lon": 54.346658,
    "radius_m": 30,
    "p_within_50m": 1.0,
    "standard": {
      "en": "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi",
      "ar": "29 شارع شبيب بن سعيد المهيري, الخالدية, أبوظبي",
      "postcode": "20039"
    },
    "evidence": {"street_matched": "shabib bin saeed al muhairi street", "house_number": "29", "how": "exact"}
  },
  "asks": [],
  "degraded": false,
  "calibrated": true
}
```

Without the house number and city, the same street gives an area level answer and asks for the missing details:

```json
{
  "query": "Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah",
  "status": "approximate",
  "best": {"tier": "street_area", "lat": 24.466597, "lon": 54.349075, "radius_m": 315},
  "asks": ["Add the building / house number.", "Add the city / emirate."]
}
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /resolve` | Body `{"address": "...", "city": "..."}`. `city` is optional and answers a "Which city?" question. Returns the status, the best candidate, alternatives, questions to ask and the standard form. |
| `POST /resolve/batch` | CSV upload with an `address` column. |
| `GET /health` | Status, versions and checksums of the gazetteer and model. |
| `GET /config` | Attribution text and the data offer link. |
| `GET /docs` | Interactive OpenAPI documentation. |
| `GET /` | Map dashboard. |

The status is one of `resolved`, `approximate`, `ambiguous` or `unresolved`. Every response carries `degraded` and `calibrated` flags. If the model is missing or does not match the gazetteer the service either refuses to start (`TAHDEED_STRICT=1`, the default in the image) or answers with `degraded: true`. Configuration, rate limiting and logging are described in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The same functions are available on the command line: `tahdeed resolve`, `tahdeed batch`, `tahdeed eval`, `tahdeed verify` and `tahdeed bench`.

## How it works

Text in both scripts is normalised (digits, diacritics, variant letters) and mapped to a shared consonant skeleton, so that `جميرا` and `Jumeirah` meet at one key. A parser extracts house numbers, units, Makani codes, PO boxes and landmark phrases such as "near" or `بجانب`. Every run of words is looked up in a gazetteer built from OpenStreetMap (streets, districts, points of interest, cities), tolerating transliteration variants and typos, and the set of non overlapping matches that explains most of the text is chosen by dynamic programming.

From those matches the resolver generates candidates at several levels: an exact address, a point of interest, a position interpolated between neighbouring buildings, a position relative to a landmark, a street within a district, a street, an area and a city. Gradient boosted trees score each candidate, and isotonic regression fitted on districts the model never saw calibrates the scores, so that a reported probability of 0.9 corresponds to being right about nine times in ten.

A fixed policy then decides. It resolves when the calibrated probability of being within 50 m is high enough and no close rival exists. It returns an approximate area with an empirical radius when only coarse evidence is trustworthy, and otherwise marks the query ambiguous or unresolved and names the missing field. When the same name exists in several cities and the query gives no city, a city gate asks "Which city?" with the candidate cities rather than answering. The design and its measured effects are in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and [`docs/DESIGN_NOTES.md`](docs/DESIGN_NOTES.md).

## Accuracy

Generated from the result files by `scripts/make_results_blocks.py`. Intervals are Wilson 95%.

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

Queries in these benchmarks are synthetic apart from a set of 40 written by hand, and the truth is the OpenStreetMap point. The human written set is pending real data (`bench/human_kit/`). Full tables, ablations and every known failure are in [`docs/EVALUATION.md`](docs/EVALUATION.md). Predictions were written before each run and are kept with their outcomes in [`docs/PREDICTIONS.md`](docs/PREDICTIONS.md). The benchmark is described in [`bench/README.md`](bench/README.md) and reported in [`docs/BENCH_REPORT.md`](docs/BENCH_REPORT.md).

## Limitations

- No benchmark query came from a real user. Only real query logs close this gap.
- OpenStreetMap is not an official registry. When the true record is missing, the resolver can return a confident wrong neighbour (see the missing address row above). `RegistryAdapter` is an interface only and is not connected to any registry.
- A street name that exists in several cities, written without the city, is handled by the calibrated city gate. The gate lowers wrong city answers on the risk set but cannot see a record that is missing from the registry, and it costs coverage.
- Arabizi is the weakest writing style, at about 50% top 1.
- The landmark benchmark tests finding the landmark, not the offset that "near" implies.
- Makani, Onwani and National Address codes are not resolved, because those registries are not open. Dubai has few structured addresses in OpenStreetMap, so Dubai is evaluated only on point of interest queries.
- The Docker image is built and smoke tested in GitHub Actions (job `docker`).

## Data and licence

The code is released under the MIT licence (see [`LICENSE`](LICENSE)). The data are © OpenStreetMap contributors, available under the ODbL 1.0. The gazetteer derived from them is built locally by `tahdeed build` and is not committed; a small attributed fixture is included for tests. See [`data/NOTICE.md`](data/NOTICE.md) and, for the obligations of anyone serving the data publicly, section 6 of [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Project layout

```
src/tahdeed/     resolver, API, command line and evaluation code (the dashboard is in src/tahdeed/web/)
tests/           unit, property and API tests; tests/fixtures/mini.sqlite is a small gazetteer
bench/           Gulf-AddressBench datasets, scorer results and the human collection kit
docs/            model card, data card, methodology, design notes, evaluation, predictions
scripts/         reproduction, document generation and smoke test scripts
deploy/          hosting helpers (Render, Vercel, regional builds)
data/            licence notice; built data is written here and ignored by version control
```

## Documentation

[`docs/MODEL_CARD.md`](docs/MODEL_CARD.md), [`docs/DATA_CARD.md`](docs/DATA_CARD.md), [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md), [`docs/EVALUATION.md`](docs/EVALUATION.md), [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), [`docs/RELEASING.md`](docs/RELEASING.md), [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) (open data survey for Dubai addresses), [`docs/SEALED2.md`](docs/SEALED2.md) (why no second sealed set exists yet), [`docs/EDGE_PROPOSAL.md`](docs/EDGE_PROPOSAL.md). To contribute, read [`CONTRIBUTING.md`](CONTRIBUTING.md); for security reports, [`SECURITY.md`](SECURITY.md). To cite the benchmark, see [`CITATION.cff`](CITATION.cff).

## Author

Huda Mueen.
