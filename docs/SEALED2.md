# A second sealed set ("sealed2"): why none exists yet, and the policy for building one

Status: **policy only. No sealed2 data exists, and no sealed evaluation of v2.1 has been run.**
The v2.1 standard benchmark therefore has dev numbers only; the sealed column in the README is the
frozen v2.0 release, and the cross city sealed row (D9) was its one permitted use.

## Why no uninspected split exists inside the current data

1. **Every district already has a split.** Districts are assigned by `crc32(city|district) % 10`
   (`tahdeed.noise.split_of`): buckets 0 to 4 train, 5 and 6 calibration, 7 and 8 dev, 9 sealed.
   All ten buckets are in use, so there is no unassigned district to promote.
2. **The sealed bucket has been opened.** It was scored once for the v2.0 release
   (`docs/sealed/`), once for the cross city gate (D9, `docs/crosscity_sealed.json`), and the
   benchmark exports `address_sealed`, `hole_sealed`, `poi_sealed` and `crosscity_sealed` from it.
   Its aggregate numbers are known to the developer, so a decision taken after reading them would
   no longer be tested by them.
3. **Rehashing does not create fresh data.** A new salt or modulus would move train and dev
   districts into the new set. The ranker has seen their street names and the developer has read
   their error cases, so the result would be contaminated, not fresh.
4. **Newer OSM records are almost nonexistent.** Records edited after the original snapshot are
   the only OSM data nobody has inspected. `scripts/fresh_records.py` counts them in the
   2026-10-15 extract: 10 records, 3 of them new (below). That is far too small, and its
   districts are not new either.
5. **Dubai has no structured truth.** Districts without OSM addresses cannot be scored at all.

## Policy for sealed2 (to be followed when data arrives)

A sealed2 set must satisfy all of the following before anything is run on it.

| Rule | How it is checked |
|---|---|
| **Source nobody inspected.** Either (a) human written queries collected with `bench/human_kit/`, labelled by the collector, never shown to the developer; or (b) OSM address records created (version 1) after a freeze date fixed in advance, restricted to dev and sealed bucket districts, accumulated until there are at least 1,000 | (a) the collector delivers the file; (b) `scripts/fresh_records.py` with the freeze date as `--after` |
| **Committed before use.** The file's SHA-256, row count and construction command are committed to `bench/SEALED2_COMMITMENT.md`; the rows themselves are kept outside the public repository until after the run | git history shows the commitment before the result |
| **Model frozen first.** The model's `arrays_sha256`, the gazetteer SHA-256 and the gate margin are written into `docs/PREDICTIONS.md` with numeric predictions, and committed, before the set is opened | git history |
| **One run.** A single command prints aggregate metrics only (no per query output) and writes `docs/sealed2/*.json`. No change to code, model or thresholds follows from it without a new sealed set | the result file records the model and set hashes |
| **Disclosure.** After the run the rows may be published under the benchmark (human set: with the collector's consent and the licence agreed in the kit); from then on the set is "sealed2, used once" in `bench/SPLITS.md` | |

Minimum size: 1,000 rows gives a Wilson interval of about ±3 points at 65% coverage; at 400 rows it
is about ±5 points. A human set smaller than 400 rows is reported as a pilot, not as sealed2.

## Fresh OSM records in the 2026-10-15 extract

From `docs/fresh_records.json` (cutoff 2026-10-09T00:00Z; an upper bound, because records edited in
the hours before the original snapshot are also counted): of 152,359 address records (node or way
with `addr:housenumber` and `addr:street`), **10** were edited after the cutoff and **3** were
created after it; 3 of the 10 lie in the Abu Dhabi emirate bounding box. At about one new record
every two days, rule (b) would take years to reach 1,000 rows. **The human written set is the only
realistic source of sealed2**, which is why it is the first funded step in `docs/EDGE_PROPOSAL.md`.
