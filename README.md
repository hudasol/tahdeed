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
- an explanation of which parts of your text matched which gazetteer fields.

It runs offline and deterministically. No LLM and no API keys are involved.

## What it does not do

- It is not a map or a routing engine.
- It cannot resolve official Makani or Onwani identifiers, because those registries are not open. It validates Makani format and exposes an adapter interface.
- Coverage depends on OpenStreetMap. Abu Dhabi emirate has structured, bilingual address data; **Dubai addressing in OSM is sparse**, so Dubai results are reported separately and are weaker.

## Data and licence

- Code: MIT (see `LICENSE`).
- Data: © OpenStreetMap contributors, ODbL 1.0. The full derived gazetteer is built locally by the build command and is not committed. A small attributed fixture is included for tests. See `data/NOTICE.md`.

## Results (sealed split: held-out districts, run once)

| | |
|---|---|
| Answers it is confident about | 65.5% of queries, **98.7% of them within 50 m** |
| Forced top-1 within 50 m | 68.3% (char n-gram TF-IDF baseline: about 25 points lower on the mixed benchmark) |
| Calibration (ECE of P(within 50 m)) | 0.030 held-out, 0.039 with holes, 0.054 on POI queries |
| Independent generator (Latin text produced from Arabic names) | 66.0% forced top-1, 97.2% precision of confident answers; Arabizi 53.7% |
| When the true address is missing from the registry | confident answers are 86.6% right (calibration holds, precision cannot) |
| Latency / load | 5.8 ms median, 156 q/s on one core; 8 s load, 490 MB RSS |

Caveats: queries are synthetic (plus 40 hand-written ones), truth is OpenStreetMap, Dubai is evaluated only on POI queries. Two of the seven final predictions missed (sealed top-1 4.4 points under dev; POI calibration 0.054 vs 0.04 predicted). Full tables, ablations and every known failure: [`docs/EVALUATION.md`](docs/EVALUATION.md).

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
tahdeed train                                   # ~5 min, writes data/models/ranker.npz (no pickle)
tahdeed resolve "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi"
tahdeed batch addresses.csv resolved.csv        # CSV with an `address` column
tahdeed eval                                    # regenerates the evaluation numbers
tahdeed serve                                   # API + map dashboard at http://127.0.0.1:8000
```

API: `POST /resolve {"address": "..."}`, `POST /resolve/batch` (CSV upload), `GET /health`, docs at `/docs`.

Tests run against a small committed fixture (`tests/fixtures/mini.sqlite`, an OSM excerpt around Al Khalidiyah): `pytest`.

## Honest limits

- **Synthetic queries.** No query in any benchmark came from a real user. The largest open gap; only real logs close it.
- **OSM is not an official registry.** A missing record yields a confident wrong neighbour (86.6% precision when the address is absent). `RegistryAdapter` is an interface only and is not wired in.
- **Common street names across cities.** Written without the city, a coarse key can merge a street word with an area word and answer confidently in the wrong place (seen once in the 40-row gold set, over 100 km off). Documented, not fixed.
- **Arabizi** is the weakest style (about 50%).
- **Landmark benchmark** tests finding the landmark, not the offset "near" implies.
- Does not resolve official Makani / Onwani / National Address codes. Dubai structured addresses are thin in OSM.
- The Dockerfile has never been built in the development environment.

## Author

Huda Mueen.
