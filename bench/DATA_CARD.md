# Data card: Gulf-AddressBench v1.0.0

**What it is.** Query/coordinate pairs for UAE address resolution. All sets in `bench/data` except
`gold_handwritten` are **synthetic**: queries are rendered from OpenStreetMap address/POI records by templates plus noise
(abbreviation, Arabic→Latin transliteration variants, vowel drops, typos, word order, missing parts).
`gold_handwritten` (40 rows) is hand-written by the maintainer. A driver direction human written set is planned and
absent. Two further sets whose text and truth do **not** come from OpenStreetMap are described in the
next section and live in `bench/data_external`. Every row carries `"synthetic": true|false`.

**Construction.** `tahdeed bench build` runs the generators in `src/tahdeed/noise.py`, `noise2.py` and
`crosscity.py` over the dev and sealed districts of the OSM-derived gazetteer snapshot named in
`MANIFEST.json`, with the seeds listed there. Rows keep the truth coordinate, truth city, the OSM element
(`truth_ref`), the stratum, the evidence level (cross-city) and the noise tags. `hole` rows mark queries
whose truth record is meant to be absent from the reference index (a coverage hole).

**Sets.** See `SPLITS.md` and `MANIFEST.json`. `crosscity_*` pairs the same record at three evidence
levels (street+number only / + district / + city) for names that exist in several cities.

**Licence and attribution.**
- Rows contain OpenStreetMap-derived text and coordinates. The dataset files in `bench/data/` are a
  *Derived Database* of OSM and are offered under the **Open Database License (ODbL) 1.0**.
  Attribution: **© OpenStreetMap contributors** (https://www.openstreetmap.org/copyright).
- Share-alike: if you publish a database derived from these files, license it under ODbL as well.
  A *Produced Work* (a paper, a chart, aggregate scores) may use any licence but must credit OSM.
- The code (generators, scorer) is MIT, see the repo `LICENSE`. The code licence does not relax the ODbL on the data.
- Baseline prediction files contain coordinates taken from OSM-derived gazetteer records (Tahdeed, naive).
  Nominatim predictions are stored only as aggregate scores plus a request cache that is not
  redistributed (`*.cache.json` is git-ignored).
- Nominatim was queried at ≤1 request/second with an identifying User-Agent on a small sample, per
  https://operations.osmfoundation.org/policies/nominatim/. Its output is a competitor baseline and is
  **never** used as ground truth.

**Personal data.** None intended. OSM address and POI records describe buildings and businesses; no
volunteer text is included in `bench/data`. The external sets are filtered for personal data (below).

**Known limitations.**
1. **OSM is both truth and index source** in `bench/data`. A system that indexes OSM is advantaged, and
   where OSM is wrong or offset the truth is wrong by the same amount. "Within 50 m" is relative to OSM,
   not to the doorstep. The external sets below remove this circularity for the text and the truth;
   they do not make the truth correct.
2. **Synthetic queries.** Generated noise does not match how people write. Tahdeed lost accuracy from
   generator to hand-written text in earlier reviews; treat synthetic numbers as upper-ish bounds
   until the human set exists.
3. **Coverage is lopsided.** About 85% of structured address points are in Abu Dhabi emirate. Dubai
   and northern emirates are mostly POIs. Per-emirate claims would need per-emirate sets.
4. **Truth city is the record's city tag** (gold: the city tag of the registry record at the truth point), which can
   disagree with administrative boundaries near city edges.
5. **Cross-city set composition** (collisions and holes) is chosen to expose a known failure; its
   rates are *not* prevalence estimates for real traffic.

## Independent real text sets (`bench/data_external`)

Built by `tahdeed bench fetch-external` (`src/tahdeed/bench_external.py`). They answer the main weakness
of the other sets: there the text is generated from OpenStreetMap records and the truth is OpenStreetMap.
Here the text is written by businesses or by Wikidata editors, and the truth is the source's own
coordinate. The text is **not synthetic** (`"synthetic": false`, `text_kind` is `business_written` or
`human_written`) and it is **not driver direction style**: it is how a business or an editor writes a
place and its address. Rows use the same fields as `bench/data`, so the same scorer applies
(`tahdeed bench score ... --data bench/data_external`). Counts, seed, release and SHA-256 are in
`bench/data_external/MANIFEST.json`.

| Set | Source | Query text | Truth | Strata |
|---|---|---|---|---|
| `overture_places` | Overture Maps Places, release `2026-10-21.0`, UAE rows with a free text address and confidence at least 0.7 | place name, then the address string as written (Arabic, English or mixed) | the place coordinate of the record | stratified by the nearest city centre of the truth point: Dubai 1,000, Abu Dhabi 1,000, Sharjah 500, other 500; seed `20261028`; at most 3 rows per normalised name |
| `wikidata_addresses` | Wikidata via query.wikidata.org, retrieval date in the manifest | item label, then the street address statement (P6375) or street (P669) with house number (P670) | the item's coordinate (P625) | `address_statement`, `street_statement`; every qualifying item, no sampling |

**Licences, kept apart from the ODbL files.** These files are not an ODbL Derived Database and hold no
OpenStreetMap data. Overture Places rows are CDLA-Permissive-2.0, with Apache-2.0 (Foursquare) or CC0-1.0
(AllThePlaces) added where those sources contributed; the licence and dataset of every row are in the
row (`source_licenses`, `source_datasets`). Wikidata is CC0-1.0. The attribution text and licence links are
in `bench/data_external/NOTICE.md`. Do not merge these rows into the ODbL files.

**Personal data.** Phone numbers, email addresses and web links are never selected, and any row whose
name or address contains one is dropped (the repository PII guard `src/tahdeed/privacy.py` plus a link
check). Only public venue categories are kept (restaurants, cafes, hotels, hospitals, clinics, schools,
malls, banks, mosques, parks, government offices and similar). Names that look like a person, names with a
personal title, and addresses that look like a residence (villa, flat, apartment, house number) are dropped,
conservatively: any doubt removes the row. Wikidata items that are people are excluded. Tests for each rule
are in `tests/test_bench_external.py`.

**Limitations of the external sets.**
1. **Truth noise.** The truth is a source coordinate. For Overture it may be a building or mall centre,
   an approximate geocode of the address string, or a position copied between data providers. A correct
   answer at the shop door can be 100 m or more from this truth. Absolute accuracy figures are therefore
   lower bounds on real accuracy, and differences between systems are more reliable than the levels.
2. **Overture addresses are free text and noisy.** Many strings lack a city, mix Arabic and English, carry
   unit and floor details, plus codes or a PO box, or describe the wrong place. Dubai strings are
   especially irregular. The set deliberately keeps them as written. Some category labels are wrong
   (for example an office tagged as a hotel); the category is a source label, not checked.
3. **Wikidata is small and skewed.** The set is small, and the item count is stated in the manifest. It
   covers notable places: towers, hotels, malls, museums, universities, and a few schools and
   restaurants, mostly in Dubai. Many address statements were copied by editors from business web sites
   or map services, and some coordinates may likewise have been imported from another map (possibly OSM).
   The text is independent of OSM; the provenance of each coordinate is not audited.
4. **Strata and city labels are geometric.** The stratum and `truth_city` are the nearest city centre of
   the truth point from `src/tahdeed/geo.py`, not an administrative boundary. Points near city edges
   (Ajman, Umm Al Quwain, Sharjah and Dubai suburbs) may be labelled with a neighbouring city. The
   `city` a system returns is compared with that label.
5. **Sample, not census.** The Overture rows are a stratified random sample of UAE places with a
   free text address, capped per name; rates here are not prevalence estimates for all UAE places.
   Chains and large venues are over represented relative to small shops because they have more records.
6. **Release dependence.** Overture changes every release. The release is pinned and the committed
   JSONL files are the benchmark; re running the builder against another release gives different rows.
7. **Contamination.** `never seen by developers`: no ranker, calibration, gate or gazetteer decision used
   these rows, and Tahdeed was run on them once, after the predictions in `docs/PREDICTIONS.md` section G
   were committed. See `SPLITS.md` for a disclosure about an earlier coverage measurement.

**Baselines.** Public Photon and Nominatim are competitors and are never used as truth. They were
queried at no more than one request per second with the User-Agent
`tahdeed-bench/1.0 (+https://github.com/hudasol/tahdeed)` on small even stride samples, and their raw
responses (OSM derived) are cached locally and not redistributed. No commercial geocoder is used.
