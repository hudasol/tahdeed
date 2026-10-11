# Human-written benchmark: collection kit

This folder lets you collect a **human-written** test set for Tahdeed from 25 to 40 volunteers and evaluate the resolver on it. It contains tooling and templates only. **It contains no volunteer data and never will in this repo until you collect it**; do not add invented queries here.

Volunteers describe, in their own words (Arabic, English, Arabizi or a mix), how they would tell a taxi or delivery driver to reach 5 named **public** places. Each description is scored against the verified coordinate of that place.

## Contents

| File | Purpose |
|---|---|
| `CONSENT.md`, `CONSENT.ar.md` | Consent / information text (template: review it, ethics approval if required) |
| `INSTRUCTIONS.md`, `INSTRUCTIONS.ar.md` | One-page volunteer instructions with 2 invented examples |
| `PROTOCOL.md` | Organiser protocol: recruiting, avoiding priming, storing, submitting, using results |
| `places.csv`, `places_sources.md` | 60 public places with coordinates, verification level and sources |
| `build_places.py` | Rebuilds the two files above from OSM (local gazetteer) and Wikidata |
| `assign.py` | Deterministic, balanced assignment of 5 places per volunteer and personalised forms |
| `form/index.html` | Offline bilingual (EN/AR, RTL) form; no network, cookies or analytics |
| `form/schema.json`, `form/responses_template.csv` | Response-file schema; CSV layout for transcribed answers |
| `../../src/tahdeed/human.py` | `ingest` and `evaluate` (`python -m tahdeed.human ...`) |

## Step by step

1. **Review the paperwork.** Read `CONSENT.md` and `CONSENT.ar.md`, replace `<OWNER_CONTACT>`, `<PUBLICATION_DATE>`, `<DELETE_RAW_BY>`, and the licence if you do not want CC BY-SA 4.0 (also edit the form's consent text). Get ethics approval if your institution requires it. Read `PROTOCOL.md`.
2. **Check the places.** `places.csv` has 60 places (10 at verification level A, 50 at B; see `places_sources.md`). Delete rows you do not want. To rebuild: `PYTHONPATH=src python bench/human_kit/build_places.py --gazetteer data/gazetteer.sqlite` (needs network for Wikidata).
3. **Recruit** 25 to 40 volunteers with a spread of emirates, backgrounds, ages and writing habits (`PROTOCOL.md`, section 2).
4. **Create sheets and forms** (keep the output in a private folder, out of git):

   ```
   python bench/human_kit/assign.py --n 35 --out private/sheets          # writes private/sheets/codes.txt
   python bench/human_kit/assign.py --codes private/sheets/codes.txt --out private/sheets \
          --form bench/human_kit/form/index.html
   ```

   This gives `form_<code>.html` for each volunteer (their 5 places by name and category only), `<code>.json`, and `assignment_key.csv` (which code got which places; do not share). The printed report shows coverage per place and by category and emirate.
5. **Distribute** `form_<code>.html` plus the instructions. The volunteer fills it in offline, clicks **Download my responses**, and sends back `tahdeed_responses_<code>.json`.
6. **Collect** the files into a private, encrypted folder `private/responses/`.
7. **Ingest** (validates against `form/schema.json`, drops incomplete and duplicate entries, redacts phones, emails, Emirates IDs, @handles, links and long digit strings, flags possible personal addresses, replaces codes by a salted hash):

   ```
   python -m tahdeed.human ingest private/responses/*.json --out private/human.jsonl --salt-file private/salt.txt
   ```

   Open `private/human.jsonl`. For every record whose `flags` contain `review:...`, delete the line (personal address) or remove the flag (a harmless landmark). Keep `salt.txt` private.
8. **Evaluate** (needs the gazetteer and model, `data/gazetteer.sqlite` and `data/models/ranker.npz` by default):

   ```
   python -m tahdeed.human evaluate private/human.jsonl --json private/human_results.json
   ```

   Options: `--db`, `--model`, `--places`, `--levels A` (only level-A places), `--include-flagged`.
9. **Publish** only after the checks in `PROTOCOL.md` section 6.

With fewer than 20 usable descriptions, or a missing file, `evaluate` prints `pending real data` and produces no numbers.

## What this will report

A **separate, human-written evaluation set** (never pooled with the synthetic or gold sets). For all descriptions and then per script (`ar`, `en`, `arabizi`, `mixed`; detected by a simple heuristic):

- **N descriptions** and **N volunteers**,
- the **status mix** (`resolved` / `approximate` / `ambiguous` / `unresolved`),
- the share of descriptions whose top candidate is **within 50 m, 200 m and 1 km** of the verified place, with **Wilson 95% intervals** (a description without a candidate counts as a miss),
- **precision at 50 m and 200 m among `resolved` answers only**, with Wilson 95% intervals,
- a **name-only control** (the same place name without the description) next to each number, so you can see what the description adds.

How to read it:

- The resolver receives `"<place name>, <volunteer text>"`. A volunteer text says how to *reach* a public place, so many have no formal address (street, building number). The benchmark measures that honestly and low exact-position rates are expected; the useful signals are the status mix (does it abstain when it should) and the 200 m / 1 km rates.
- **Circularity warning:** the listed places are OpenStreetMap features and the resolver's gazetteer is built from the same OSM data, so the place name alone often resolves to the right spot (hence the name-only control). This benchmark therefore mainly shows whether the volunteer's description *helps or hurts* beyond the name, and how the resolver abstains; it is not a test of finding unknown places.
- For large sites (malls, campuses, parks) the truth point is a centroid, so 50 m is a hard bar. `--levels A` restricts to places whose OSM and Wikidata coordinates agree.
- Intervals assume independent descriptions; they are clustered by volunteer and place, so treat them as optimistic. With about 150 descriptions a Wilson interval on a 50% rate is roughly +/- 8 points overall and wider for each script.
- Do not tune the resolver on this set.

## Tests

`PYTHONPATH=src python -m pytest -q -p no:warnings tests/test_human_kit.py` uses small **synthetic test fixtures** created inside the tests (labelled as such). They are never data and never written under `bench/`.
