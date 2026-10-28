# Candidate open data sources for UAE addresses

Research note, accessed **2026-10-11**. Question: can a legitimately open source add structured addresses
(house number + street + district + city) to the OSM-only, ODbL gazetteer, above all for Dubai?

**Short answer: no source found is both usable and structured for Dubai.** Dubai's authoritative address
register (Makani) is not published as a bulk open dataset, and its terms conflict with an ODbL derivative.
The only open, licence-compatible source with sizeable Dubai coverage is Overture *Places*, and it
carries noisy free-text addresses, not structured ones.

Method: official pages read with WebFetch/WebSearch; no scraping, no auth bypass. Overture and GeoNames
were reached through the sandbox proxy and queried with a tiny bbox/count query (no data kept).
Quotes are as returned by the fetch tool (some are paraphrased by it; marked "paraphrase"). Anything
unconfirmed says **not verified**.

## Verdict table

| Source | Accessible now? | Licence allows our use? | Structured Dubai addresses? | Effort | Verdict |
|---|---|---|---|---|---|
| Dubai Pulse (Dubai Municipality datasets) | Request + emailed API key/secret; approval "within 14 days" | Licence field "notspecified"; no grant verified | No: building datasets have community, parcel and building id, but no street or Makani no. (Entrances not verified) | Medium; needs approval and written licence | **Blocked** until DM confirms terms in writing |
| Makani (dm.gov.ae / makani.ae) | Free "to everyone", but bulk file or API not documented | No: "not allowed ... to sell MAKANI data"; no altering; unspecified AUP | Yes in principle (register of all Dubai buildings), but no bulk release verified | High; needs DM agreement | **Blocked**; email DM for a written licence |
| Abu Dhabi SDI "OpenData" service (ADSDI) | Directory visible; login link | No: "For use by Abu Dhabi government entities only" | Layers seen: BUILDING, ADR_DISTRICT (not Dubai) | n/a | **No** |
| Onwani (DMT) | Map viewer only | "© 2023 Abu Dhabi Government. All rights reserved." | No open download | n/a | **No** |
| Bayanat (federal) | Yes | Text says "freely available ... use, reuse, distribute"; no licence named on About page | No address dataset described (Geo-Data section not inspected) | Low to check | **Check later**, low expectation |
| UAE Open Data portal (opendata.fcsc.gov.ae) | Yes | CC BY 4.0 (no share-alike) | No addresses (statistics only) | n/a | Not useful |
| Sharjah, RAK, Fujairah, UAQ portals | **Not verified** (no portal found) | Not verified | Not verified | n/a | Unknown |
| Ajman Data | Portal exists (u.ae); licence page returned no text | Not verified | Not verified | n/a | Unknown |
| Overture Addresses | Yes (public S3) | Per-source permissive licences | **No UAE rows** (0 in release 2026-09-23.1) | n/a | **No** |
| Overture Places | Yes | CDLA-Permissive-2.0, Apache-2.0, CC0-1.0 | Free-text only; ~104k Dubai POIs | Medium | **Usable as supplement, not as addresses** |
| Overture Buildings/Divisions/Base/Transportation | Yes | ODbL (OSM-derived, plus others) | No addresses | n/a | Redundant (OSM) |
| OpenAddresses | Wiki/outreach list only | n/a | **No UAE source verified** | n/a | **No** |
| GeoNames AE | Yes (345 KB zip) | CC BY 4.0 | No; place names, not addresses | Low | Optional name enrichment only |
| Wikidata | Reachable; not queried | CC0 (not re-verified) | No | Low | Optional name enrichment only |
| Google Open Buildings | Yes | CC BY 4.0 or ODbL | No (footprints); UAE not in coverage | n/a | No |
| Microsoft building footprints | Not checked | ODbL per Overture | No (footprints) | n/a | No |

## 1. Dubai

### Dubai Pulse (dubaipulse.gov.ae): exists, access is request based
- `https://www.dubaipulse.gov.ae/data/dm-general/dm_building_usages-open`: CSV, 13.87 MB, updated 31 Dec 2025.
  "Rights: Everyone", but "Users must submit a request and acknowledge the terms ... confirmation within 14 days";
  API Key + Secret "emailed to users", exchanged for a time-limited bearer token. **License: "notspecified"**.
- `.../dm_building_usages_lookup-open` (0.93 KB, updated 27 Nov 2025): same access, same "notspecified".
- `.../dm-registration/dm_building_summary_information-open` (38 fields, CSV, updated 18 Mar 2024): has
  `community_name_english/arabic`, `community_no`, `parcel_id`, `building_id`, `building_serial_no`. Per the fetch,
  **no street name, address or Makani number**. Licence "notspecified", rights blank.
- `.../organisation/dubai-municipality/service/dm-location` lists `dm_community-open`, `dm_sectors-open`,
  `dm_dmgisnet_enterances-open` (no description; contents **not verified**). No street or address dataset listed.
- DM's open data page (`https://dm.gov.ae/open-data/`): "Customers have the right to use this data and statistics at their
  own liability"; "The source of the data must be mentioned when used"; "Dubai Municipality is not liable for any data
  distortion, modification or wrong use". It names no licence, version, or redistribution/derivative terms.
- `https://www.dubai.ae/open-data`: terms are "associated" with each dataset's metadata; no licence named. The data law
  allows publication "without restriction or with the minimum restrictions specified by the competent authority"
  (secondary summary, dataprotectionreport.com 2016), so each authority sets its own terms.
- Not verified: Dubai Pulse site-wide terms text (the root page fetch was not permitted in this session), Dubai
  Statistics Center licence, robots.txt.

### Makani
- `https://www.dm.gov.ae/open-data/open-data-for-makani/`: "These free data are available to everyone"; use is subject to
  "Acceptable Usage Policies" (not linked). Quoted restrictions: "It is not allowed, however, to sell MAKANI data to anyone
  or any entity"; "Altering the content or source of this data is prohibited"; "You can use the application for profit
  purposes provided that it effectively serves the public interest"; credit "Dubai Municipality". Liability: user is
  "fully liable".
- The page links a "Makani Public Web Service" manual (`https://www.dm.gov.ae/documents/makani-public-web-service-access-pdf/`),
  **not read**, so API terms, rate limits and bulk-use rules are **not verified**. Gulf News (updated 2018-09-16) repeats
  "Makani data cannot be sold to anyone." Nothing found says scraping is allowed; do not scrape.
- DM site terms (`/website-policies/terms-and-conditions/`) are silent on scraping, but state that UAE copyright law protects site content.
- makani.ae robots.txt: **not verified** (fetch not permitted).
- OpenAddresses' own outreach wiki lists Makani only as a "potential" source, with no outcome noted.

**Why Makani/Dubai Pulse cannot go into the ODbL gazetteer as-is:** ODbL requires that anyone receiving the derived
database may use, modify and redistribute it freely, including commercially. Makani's "no selling" and "no altering"
conditions, plus an unspecified AUP, are additional restrictions we cannot pass on. Unless Dubai Municipality grants
a written licence that is ODbL-compatible (or a separate permission to publish a derivative), it stays out.

## 2. Abu Dhabi
- ADSDI "OpenData" ArcGIS service (`arcgis.sdi.abudhabi.ae/agspublish/rest/services/OpenData/ADSDI_OpenData/MapServer`):
  layer 353 BUILDING and layer 818 UDM_ADR_DISTRICT (Department of Municipal Affairs), both with licence field
  **"For use by Abu Dhabi government entities only"**, despite the "OpenData" name. Excluded.
- Onwani (`https://pages.dmt.gov.ae/en/onwani`): no data/API/terms; footer "© 2023 Abu Dhabi Government. All rights reserved."
  Contact on page: onwani_info@dmt.gov.ae.
- Statistics Centre Abu Dhabi portal (`opendata.fcsc.gov.ae`): CC BY 4.0 but statistics only (e.g. building permits).
- addata.gov.ae / data.abudhabi portal terms: **not verified** (searches returned no portal page).

## 3. Federal and other emirates
- Bayanat About page (`https://bayanat.ae/en/About`): data "freely available for anyone to use, reuse, distribute, or share
  with others"; no licence named; no address datasets described; "Geo-Data" section **not inspected**.
- UAE Open Data terms (`https://opendata.fcsc.gov.ae/p/terms-of-use`): CC BY 4.0 text (fetch tool paraphrase: commercial use,
  adaptation, redistribution allowed; credit required; no share-alike). Applies to that portal only.
- u.ae lists Dubai Pulse, Abu Dhabi Data, Ajman Data, Bayanat; it mentions **nothing** for Sharjah, RAK, Fujairah, UAQ.
  Ajman licence page (`scc.ajman.ae/en/node/37`) returned no text. UAE National Geospatial Feature Catalogue
  (`geoportal.fgic.gov.ae`) surfaced in search; **not reviewed**.

## 4. Other open sources

### Overture Maps (release `2026-09-23.1`, queried 2026-10-11 via HTTPS parquet range reads)
- Licences (`https://docs.overturemaps.org/attribution`): Addresses "comes from a variety of sources ... All carry
  permissive open licenses" (G-NAF, CC BY 4.0 Austria, CC0 NL/BR, US NAD); Base, Buildings, Divisions, Transportation
  are listed as **ODbL**; Places are per-source: "Available under CDLA Permissive 2.0" (Meta, Microsoft, etc.),
  Foursquare Apache 2.0, AllThePlaces CC0 1.0.
- **Addresses theme, UAE: zero rows.** `country in ('AE','OM','SA','QA','BH','KW')` returned nothing, and a UAE-wide bbox
  returned 0 rows (schema: street, number, unit, postcode, postal_city, address_levels, country).
- **Places theme, Dubai bbox (54.9-55.65 E, 24.75-25.45 N): 104,442 POIs.** 97,405 have `addresses[1].freeform`,
  103,680 a locality, 70,004 a postcode. Source licences in that bbox: CDLA-Permissive-2.0 (Overture/Meta/Microsoft/PinMeTo/DAC),
  Apache-2.0 (Foursquare, 5,936), CC0-1.0 (AllThePlaces, 1,162). Sample freeform values are unstructured, e.g.
  "Plot No: MO 0641 & 0642, Road No: N202 Jebel Ali,", "Office 3207, ParkLane Tower Business Bay", "Lane 1102",
  "25427 88343, شارع الشيخ زايد 15", mixed Arabic/English, `region` often null. No house-number/street split.
  Some rows carry a Makani-like number inside freeform text; reliability **not assessed**.
- Compatibility: permissive licences (CDLA-Permissive-2.0, Apache-2.0, CC0) can be added to an ODbL database as
  contents; the database as a whole stays ODbL, and the third-party notices/attribution for each source must be preserved
  (Apache/CDLA ask for notices; confirm exact wording before shipping). Do **not** mix in ODbL-labelled Overture themes
  expecting new information: they are OSM-derived.

### OpenAddresses
No UAE source verified (wiki lists Dubai/Makani as outreach only; direct repository listing was blocked by the sandbox and not worked around).

### GeoNames (`https://download.geonames.org/export/dump/readme.txt`)
"This work is licensed under a Creative Commons Attribution 4.0 License ... The Data is provided 'as is' without warranty or any representation of accuracy, timeliness or completeness."
`AE.zip` (345 KB, 8,584 rows: 2,981 spots, 2,406 populated places, 1,243 hydro/terrain...). Names and coordinates only, no streets.

### Wikidata, Google Open Buildings, Microsoft footprints
- Wikidata: CC0 is the project's published licence; not re-verified this session; no address structure.
- Google Open Buildings (source.coop): covers "Africa, South Asia, South-East Asia, Latin America and the Caribbean"; page does not mention the
  Middle East; "CC BY-4.0 ... also ... ODbL v1.0". Footprints only.
- Microsoft Global ML Building Footprints: ODbL per Overture's attribution page; UAE coverage **not verified**. Footprints only.

## What ODbL share-alike implies for combining (summary, not legal advice)
Our gazetteer is an OSM-derived ODbL database. Adding permissively licensed records (CC0, CC BY 4.0, CDLA-Permissive,
Apache-2.0) is allowed as long as the combined database is published under ODbL and each source's attribution/notice
is kept. Adding data under a more restrictive licence (Makani: no sale, no alteration; ADSDI: government-only; "all rights
reserved") is not allowed without a written, compatible grant. OSM contributors attribution stays required. ODbL
clause-by-clause reading was **not re-verified** here; check the licence text before releasing a merged database.

## Recommendations
1. Do not ingest Dubai Pulse or Makani without written permission. Ask Dubai Municipality (GIS Centre) for an explicit
   licence covering redistribution of a derived, openly licensed address database, and ask Makani for a bulk file.
2. Optional: ingest Overture Places (CDLA/Apache/CC0 rows only) as a *fallback POI name/locality index*, flagged
   `quality=freeform`, never promoted to a structured address. Parsing freeform text into fields would be new, separate work.
3. Optional: GeoNames AE as an alias source for district/place names (CC BY 4.0 attribution).
4. Revisit Bayanat Geo-Data and Sharjah/RAK/Ajman portals manually in a browser.

## Evaluated 2026-10-16: Overture Places and GeoNames as Dubai POI supplements (Phase 2, T4)

Licences checked again on 2026-10-16. Overture attribution page (<https://docs.overturemaps.org/attribution/>):
Places sources are Meta, Microsoft, PinMeTo, Krick, RenderSEO, DAC and BrightQuery under CDLA
Permissive 2.0, Foursquare under Apache 2.0 ("Copyright 2024 Foursquare Labs, Inc. All rights
reserved." plus the NOTICE file Overture links), AllThePlaces under CC0 1.0. GeoNames readme
(<https://download.geonames.org/export/dump/readme.txt>): "This work is licensed under a Creative
Commons Attribution 4.0 License". All four licences are permissive and can be added to an ODbL
database as contents, provided the combined database stays ODbL and each source's attribution and
notices are carried (see `data/NOTICE.md`).

Measured (`docs/supplements_dubai.json`, generated by `scripts/fetch_overture_dubai.py` on release
`2026-09-23.1` and `scripts/eval_supplements.py`; numbers also in `docs/EVALUATION.md`): every one
of the 104,442 Overture rows in the Dubai bounding box carries only those licences; only 9.1% of OSM
Dubai POIs in the dev split have an Overture place with the same tahdeed name key within 100 m; most
confident Overture places have no same key OSM POI nearby. GeoNames has 1,890 feature class S rows
in the box. **Mixed truth caveat:** agreement between sources is not accuracy, and exact name key
matching understates overlap between differently written names.

**Decision: nothing merged.** The terms allow it, but a merge needs (a) name matching that tolerates
the naming differences seen above and (b) a resolver evaluation whose truth is not the supplement
itself, otherwise the gain cannot be measured honestly. Both are listed as next steps in
`docs/OVERNIGHT_REPORT.md`. The downloaded rows are local working data and are not committed.
