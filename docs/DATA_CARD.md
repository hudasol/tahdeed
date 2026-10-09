# Data card: tahdeed gazetteer

**Source.** OpenStreetMap, UAE extract from `download.openstreetmap.fr` (snapshot 2026-10-09), © OpenStreetMap contributors, **ODbL 1.0**. The derived SQLite database is built locally (`tahdeed build`) and is not committed; a small bounding-box excerpt (`tests/fixtures/mini.sqlite`, Al Khalidiyah / Al Markaziyah) is committed for tests with attribution.

**Contents** (this build): 146,864 address points, 84,767 street segments, 3,105 areas, 59,511 POIs.

**Coverage, honestly.**
- ~125k *structured, bilingual* address points are in Abu Dhabi emirate (Abu Dhabi City, Al Ain, Al Dhafra), from an import aligned with the Abu Dhabi Onwani scheme. Official figures say Onwani covers ~87% of Abu Dhabi City, 79% of Al Ain, 99% of Al Dhafra; OSM's coverage of those is not independently audited here.
- Dubai, Sharjah, Ajman, RAK, Fujairah, UAQ have very few structured addresses in OSM; mostly POIs with partial address tags.
- **Selection bias**: evaluation truth is OSM itself. Where OSM is wrong or offset, "within 50 m" is wrong by the same amount.

**Fields used.** house number, street (Arabic/English), district and sub-district, city, postcode, coordinates, OSM id. Names keep both scripts when present.

**Derived indexes.** Consonant-skeleton keys (Arabic and Latin spellings map to one key), consonant-class "coarse" keys, order-insensitive keys, per-key ambiguity counts (how many distinct names share a key).

**Splits.** Districts are assigned by `crc32(city|district) % 10`: 0-4 train, 5-6 calibration, 7-8 dev, 9 sealed. No district appears in two splits.

**Personal data.** OSM address points describe buildings, not occupants. Nothing in the gazetteer identifies people. Do not combine it with occupant data without a legal basis.

**Not in the data.** Makani codes, the National Address, postal delivery points, Dubai's plot/community registry, any official identifier. tahdeed never invents these.
