# Gulf-AddressBench changelog

Versions follow the data, not the code: a change to any row, set or metric definition raises the
version; scorer refactors that leave every committed score identical do not.

## Unreleased

- CI job `bench-drift` (`scripts/check_bench_drift.py`): checks every `data/*.jsonl` against the
  SHA-256 and row count in `MANIFEST.json`, scores each committed prediction file again, and requires
  the result and `docs/BENCH_REPORT.md` to match the committed files exactly. No data or score changed.
- `CITATION.cff` and `codemeta.json` added. No DOI has been minted.
- No new set. A second sealed set is not available; see `docs/SEALED2.md`.

## 1.0.0 (2026-10-11)

- First release: `address_dev`, `address_sealed`, `hole_dev`, `hole_sealed`, `poi_dev`, `poi_sealed`,
  `landmark_dev`, `crosscity_dev`, `crosscity_sealed`, `gold_handwritten` (counts, seeds and
  hashes in `data/MANIFEST.json`), built from the gazetteer whose SHA-256 is in the manifest
  (OpenStreetMap extract of 2026-10-09).
- Scorer (`tahdeed bench score`) with answered share, precision at 50 m, wrong city among answered,
  end to end at 50 m and forced at 1 km, all with Wilson 95% intervals.
- Baselines: tahdeed (v2.1 development model), naive fuzzy matcher, public Nominatim on a
  rate limited sample of at most 100 queries per set.
