# tahdeed · تحديد

**Bilingual Arabic/English address resolver for the UAE.** It turns messy free-text addresses into coordinates, an Onwani-style standard form and a calibrated confidence score, and it abstains when an address is too ambiguous.

> **Status: v1.0.** Resolver, calibration, evaluation, API, CLI and dashboard are complete. Method and plan: [`plan.md`](plan.md). Results and failure analysis: [`docs/EVALUATION.md`](docs/EVALUATION.md).

## The problem

The UAE has no single address a program can rely on. Dubai uses Makani (a 10-digit code per building entrance, Dubai only). Abu Dhabi uses Onwani (building number, street, city). The federal National Address is a specification that aggregates the emirates' systems, not an open layer an app can call. Meanwhile people write "Villa 14, near the Spinneys, Jumeira 3" or "شارع الأسد بجانب المطعم", and every place has several spellings because Arabic names are transliterated in many ways.

tahdeed is a **translation layer** between how people write addresses and the keys official systems use, and it is explicit about when it cannot tell.

## What it does

Given a free-text address (Arabic, English or mixed), it returns:

- ranked candidate locations with an uncertainty radius,
- a standardized bilingual address (building / street / district / city / postcode where known),
- a calibrated confidence: the probability that the top candidate is within a stated distance of the truth,
- an abstain / ask decision naming the missing field (for example "add a building number"),
- an explanation of which parts of your text matched which gazetteer fields.

It runs offline and deterministically. No LLM and no API keys are involved.

## What it does not do

- It is not a map or a routing engine.
- It cannot resolve official Makani or Onwani identifiers, because those registries are not open. It validates Makani format and exposes an adapter interface.
- Coverage depends on OpenStreetMap. Abu Dhabi emirate has structured, bilingual address data; **Dubai addressing in OSM is sparse**, so Dubai results are reported separately and are weaker.

## Data and licence

- Code: MIT (see `LICENSE`).
- Data: © OpenStreetMap contributors, ODbL 1.0. The full derived gazetteer is built locally by the build command and is not committed. A small attributed fixture is included for tests. See `data/NOTICE.md`.

## Results (synthetic noisy queries on held-out districts)

| | |
|---|---|
| Answers it is confident about | 61.9% of queries, **98.1% of them within 50 m** |
| Calibration (ECE of P(within 50 m)) | 0.020; candidates scored 0.9-1.0 are right 99.0% of the time |
| Forced top-1 within 50 m | 64.6% (naive fuzzy baseline 54.8%, public Nominatim 45.0% on a 200-query sample) |
| Latency | 5 ms median per query, CPU only |

Caveats: queries are synthetic, truth is OpenStreetMap, Dubai is only evaluated on POI queries, and when the true address is missing from the registry about 29% of confident answers are a wrong neighbouring building. Predictions were not pre-registered before the run, despite the plan. Full tables and every known failure: [`docs/EVALUATION.md`](docs/EVALUATION.md).

## How it works

1. **Normalise** Arabic and Latin text (digits, diacritics, alef/ya variants) and map both scripts to a shared consonant skeleton, so `جميرا` and `Jumeirah` meet at one key.
2. **Parse** house numbers, units, Makani, PO boxes and landmark phrases ("near", "opposite", `بجانب`).
3. **Match** every n-gram of the text against a gazetteer built from OSM (street, district, POI, city), tolerating transliteration and typos.
4. **Generate candidates at several levels**: exact address, POI, interpolated between neighbouring buildings, landmark-relative, street + district, street, area, city.
5. **Score** each candidate with gradient-boosted trees, then calibrate with isotonic regression on districts the model never saw, so 0.9 means right about 9 times in 10.
6. **Decide**: resolved, approximate (an area with an empirical 90% radius), ambiguous, or unresolved, and ask for the missing field.

## Quick start

```bash
pip install -e ".[dev,build]"

# OSM extract: https://download.openstreetmap.fr/extracts/asia/united_arab_emirates.osm.pbf
tahdeed build united_arab_emirates.osm.pbf      # ~30 s, writes data/gazetteer.sqlite
tahdeed train                                   # ~2 min, writes data/models/ranker.pkl
tahdeed resolve "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi"
tahdeed batch addresses.csv resolved.csv        # CSV with an `address` column
tahdeed eval                                    # regenerates the evaluation numbers
tahdeed serve                                   # API + map dashboard at http://127.0.0.1:8000
```

API: `POST /resolve {"address": "..."}`, `POST /resolve/batch` (CSV upload), `GET /health`, docs at `/docs`.

Tests run against a small committed fixture (`tests/fixtures/mini.sqlite`, an OSM excerpt around Al Khalidiyah): `pytest`.

## Limitations

- Does not resolve official Makani / Onwani / National Address codes (registries are not open).
- Quality follows OSM coverage: strong for Abu Dhabi, Al Ain and Al Dhafra, thin for structured Dubai addresses.
- Consonant-changing transliterations (`kh`→`k`, `q`→`g`) remain the weakest case.
- The noise model is ours; real user data would change the numbers.

## Author

Huda Mueen.
