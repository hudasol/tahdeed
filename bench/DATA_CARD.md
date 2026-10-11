# Data card: Gulf-AddressBench v1.0.0

**What it is.** Query/coordinate pairs for UAE address resolution. All sets except `gold_handwritten`
are **synthetic**: queries are rendered from OpenStreetMap address/POI records by templates plus noise
(abbreviation, Arabic→Latin transliteration variants, vowel drops, typos, word order, missing parts).
`gold_handwritten` (40 rows) is hand-written by the maintainer. A human-written set is planned and
absent. Every row carries `"synthetic": true|false`.

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

**Personal data.** None. OSM address and POI records describe buildings and businesses; no volunteer
text is included in v1.

**Known limitations.**
1. **OSM is both truth and index source.** A system that indexes OSM is advantaged, and where OSM is
   wrong or offset the truth is wrong by the same amount. "Within 50 m" is relative to OSM, not
   to the doorstep.
2. **Synthetic queries.** Generated noise does not match how people write. Tahdeed lost accuracy from
   generator to hand-written text in earlier reviews; treat synthetic numbers as upper-ish bounds
   until the human set exists.
3. **Coverage is lopsided.** About 85% of structured address points are in Abu Dhabi emirate. Dubai
   and northern emirates are mostly POIs. Per-emirate claims would need per-emirate sets.
4. **Truth city is the record's city tag** (gold: nearest city centre to the truth point), which can
   disagree with administrative boundaries near city edges.
5. **Cross-city set composition** (collisions and holes) is chosen to expose a known failure; its
   rates are *not* prevalence estimates for real traffic.
