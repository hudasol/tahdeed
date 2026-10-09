# tahdeed · تحديد

**Bilingual Arabic/English address resolver for the UAE.** It turns messy free-text addresses into coordinates, an Onwani-style standard form and a calibrated confidence score, and it abstains when an address is too ambiguous.

> Status: under construction. See [`plan.md`](plan.md) for the problem statement, method and pre-registered evaluation. This README is updated as each milestone lands.

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

## Quick start

Commands are added as the corresponding milestones land (see the table of milestones in `plan.md`).

```bash
pip install -e ".[dev]"
```

## Author

Huda Mueen.
