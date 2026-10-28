# Notice and licences for bench/data_external

These files are **separate from the OpenStreetMap derived files in `bench/data`**. They are not an
ODbL Derived Database, they contain no OpenStreetMap data, and they must not be merged into the
ODbL files. Each file has the licence stated below. The code that builds them
(`src/tahdeed/bench_external.py`) is MIT, as the rest of the repository.

## `overture_places.jsonl` (3,000 rows)

Place names, free text address strings and place coordinates from **Overture Maps Places**,
release `2026-10-21.0`, read anonymously from the public bucket
`s3://overturemaps-us-west-2/release/2026-10-21.0/theme=places/type=place/`.

Attribution: **Overture Maps Foundation, Places theme (https://overturemaps.org), with data from
Meta, Microsoft, Foursquare, AllThePlaces, Uberall and OpenTravel as recorded per row.**

The licence of every row is recorded in the fields `source_licenses` and `source_datasets`, copied
from the `sources` property of the Overture record. Three licences occur:

| Licence | Source datasets | Text |
|---|---|---|
| CDLA-Permissive-2.0 | Overture, Meta, Microsoft, Uberall, OpenTravel | https://cdla.dev/permissive-2-0/ |
| Apache-2.0 | Foursquare | https://www.apache.org/licenses/LICENSE-2.0 |
| CC0-1.0 | AllThePlaces | https://creativecommons.org/publicdomain/zero/1.0/ |

Every row carries CDLA-Permissive-2.0 (the Overture record itself); rows that also draw on
Foursquare or AllThePlaces additionally list Apache-2.0 or CC0-1.0. Redistribution under these
licences requires that the licence text is available to recipients; the links above serve that
purpose. The data are provided as is, without warranty.

What was removed: phone numbers, e-mail addresses and web links (never selected from the source;
rows whose name or address contains any are dropped), categories that are not public venues, names
that look like a private person, titles such as "Dr", and addresses that look like a private
residence (villa, flat, apartment, house number). The filter is conservative on purpose and drops
rows on doubt. If you find a row that should not be here, open an issue and it will be removed.

## `wikidata_addresses.jsonl`

Labels, address statements (property P6375 "street address", or P669 "located on street" with P670
"house number") and coordinates (P625) of UAE items from **Wikidata**
(https://www.wikidata.org), retrieved through https://query.wikidata.org on the date recorded in
`MANIFEST.json`. Wikidata structured data is available under **CC0 1.0**; no attribution is
required, and it is given here nonetheless: *Wikidata contributors*. Items that are instances of
"human" are excluded.

## Truth and its limits

The truth of every row is the coordinate of the source record. It is not surveyed. It can be wrong,
imprecise (a mall centre rather than a shop door) or, for Wikidata, copied from another map by an
editor. The text is human or business written and is neither synthetic nor driver direction style.
The row field `synthetic` is `false`; `text_kind` is `business_written` or `human_written`.
See `bench/DATA_CARD.md`.
