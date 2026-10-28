# Split policy and contamination

Districts are assigned to splits by `crc32(city|district) % 10`: 0-4 train, 5-6 calibration, 7-8 **dev**,
9 **sealed**. No district is in two splits. Tahdeed's ranker is trained on train and calibrated on
calibration districts only. The benchmark exports only dev and sealed districts.

"Contamination" below means *how much the Tahdeed developers have looked at or tuned against the set*.

| Set | Source districts | Status | What that means |
|---|---|---|---|
| `address_dev`, `hole_dev`, `poi_dev`, `landmark_dev` | dev | **dev-seen** | Used for model selection, error analysis and ablations over five review rounds. Treat Tahdeed's numbers as optimistic |
| `crosscity_dev` | dev | **dev-seen** | Used to design the city gate and choose its margin (0.35); five predictions were falsified on it, recorded in `docs/PREDICTIONS.md` |
| `address_sealed`, `hole_sealed`, `poi_sealed` | sealed | **sealed** | Generated with fixed seeds; Tahdeed's headline sealed run (`docs/sealed/`) used the *standard* generator with different seeds, so these exact queries were not scored before, but the *districts* were the sealed split |
| `crosscity_sealed` | sealed | **sealed, used once** | One run, after the final model and margin were fixed (prediction D9) |
| `gold_handwritten` | dev-adjacent | **seen throughout development** | 40 queries written by the maintainer while building the system; failures were fixed. Contaminated; a smoke test only |
| `overture_places`, `wikidata_addresses` | external, not OSM | **never seen by developers** | Built after the model was frozen. Tahdeed ran on them once, after `docs/PREDICTIONS.md` section G was committed; nothing was tuned on them. Disclosure: an earlier task (T4) downloaded Overture Places rows in a Dubai box to size coverage against OSM; it changed no model or gazetteer, and the rows here were drawn afresh from the whole UAE. They are in `data_external/`, outside the district split (the split policy above does not apply to them) |
| `human_v1` | not collected | **pending real data** | No data exists. See `human_kit/` |

Anything not listed was never evaluated. Sealed sets lose their value once anyone tunes against them;
if you do, say so. New sealed material should come from newly collected data (the human set).

**A second sealed set.** None exists yet: every district is already in a split and the sealed bucket
has been opened. The policy for building one, and the count showing why fresh OSM records cannot
supply it, are in [`docs/SEALED2.md`](../docs/SEALED2.md).
