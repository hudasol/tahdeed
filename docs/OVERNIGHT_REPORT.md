# Overnight report, 2026-10-16

Branch `phase2-crosscity-bench` (PR #1, still open, not merged). Every number below is copied from
the result file named next to it; the generated documents (`docs/EVALUATION.md`,
`docs/EDGE_PROPOSAL.md`, README and model card blocks) are rendered from the same files, and a new
CI job fails if they drift.

## Two things to know first

1. **The original OSM snapshot is gone.** The extract behind every published number (2026-10-09,
   sha256 `875a1a23...`) is no longer offered by the mirror, which keeps only the latest file. All
   new experiments ran on the 2026-10-15 extract (sha256 `a0d00fee...`) with every model retrained
   on it, so comparisons inside each experiment are like for like. Published v2.0 and v2.1 numbers
   were not regenerated, because no model was replaced. Only 10 address records changed between the
   two snapshots (`docs/fresh_records.json`).
2. **Compute was the bottleneck.** The machine slept for a few hours and other jobs shared the CPU,
   so one training run took about 1.5 hours. Second and third training seeds were not run.

## What changed, per task

| Task | Outcome | Main files |
|---|---|---|
| T1 POI calibration | Diagnosed by ablation over five retrained models; no fix adopted under the pre-registered rule; trade off documented | `docs/poi_ablation.json`, EVALUATION.md T1 section |
| T2 "Which city?" | `city` hint in resolver, API, batch CSV, CLI and dashboard; measured | `docs/clarify_dev.json`, `tests/test_city_hint.py` |
| T3 sealed2 | No uninspected split exists; policy written; no sealed v2.1 run | `docs/SEALED2.md` |
| T4 Dubai sources | Licences checked; Overture and GeoNames sized against OSM; nothing merged; Makani letter drafted, not sent | `docs/supplements_dubai.json`, `docs/outreach/makani_request.md` |
| T5 demo build | Reproducible Abu Dhabi emirate build with its own model; memory measured; not deployed | `deploy/build_demo_region.sh`, `docs/region_rss.json`, DEPLOYMENT.md 5.6 |
| T6 last meter | Exploratory module, extraction and evaluation against OSM mapped entrances | `src/tahdeed/lastmeter.py`, `docs/lastmeter_eval.json` |
| T7 citation | `CITATION.cff`, `codemeta.json`, `bench/CHANGELOG.md`, CI job `bench-drift` | `scripts/check_bench_drift.py` |
| T8 one pager | Rendered from result files, about 770 words | `docs/EDGE_PROPOSAL.md` |
| T9 review | Style pass (em dashes and unneeded hyphens removed); review checks below | this file |

Also: `gc.freeze()` before forking workers (a training run stalled 30 minutes without it), and a
CI job `docs-regen` that fails when a generated document differs from its script's output.

## Headline numbers (copied from the result files)

- **T1** (`docs/poi_ablation.json`, dev, 2026-10-15 extract). Dubai POI ECE: v2.1 model 0.103
  (bootstrap 0.090 to 0.117); v2.0 training 0.066; without the cross city mix 0.064; with the two new
  features masked 0.102; gate and diversification move it by less than 0.001. Without the mix's
  `poi_hole` rows: 0.072, but address risk set wrong city exposure at gate 0.35 rises from 2.2%
  (1.6 to 3.0) to 7.7% (6.5 to 9.1). Model kept.
- **T2** (`docs/clarify_dev.json`, dev). 248 of 1,498 non hole E0 queries were asked "Which
  city?"; with the true city supplied, 247 resolve within 50 m, 99.6% (97.8 to 99.9); none resolves
  more than 50 m away.
- **T3** (`docs/fresh_records.json`). 10 of 152,359 address records were edited after the original
  snapshot, 3 created.
- **T4** (`docs/supplements_dubai.json`). 104,442 Overture rows in the Dubai box, all under
  CDLA Permissive 2.0, Apache 2.0 or CC0; 9.1% (7.9 to 10.4) of 2,034 OSM dev Dubai POIs have an
  Overture place with the same name key within 100 m (median 17.8 m); GeoNames has 1,890 class S
  rows there.
- **T5** (`docs/region_rss.json`). Abu Dhabi emirate build: 362 MB resident after load, peak
  369.9 MB, under Render's free 512 MB.
- **T6** (`docs/lastmeter_eval.json`, exploratory, OSM derived labels). 242 buildings, 410 mapped
  entrances. Within 10 m of a mapped entrance: footway or service way end 59.9% (53.6 to 65.9, partly
  label leakage), centroid 29.8%, outline point facing the road 24.0%, nearest road point 11.6%.

## How the final review was done

An independent review agent was started twice and stalled both times without reporting, so the
final review was a set of scripted checks instead: (1) the text of all 22 Phase 2 predictions is
identical to the commit that registered it (only the Result column changed); (2) every number in
this report matches its JSON source; (3) no em dashes, emojis, university name or mention of AI
assistance in the new documents or in any commit message on this branch; (4) all generated
documents regenerate with no diff, which CI now enforces (`docs-regen`). Earlier fixes found during
the work: footways treated as roads in the last meter module (caught by a test, fixed before its
evaluation), a T2 sentence that wrongly said every hole answer is wrong, and Wilson bounds printing
as -0.0. A full independent code review of the new modules is still worth doing before merge.

## Predictions: hits and misses

| Set | Hits | Misses | Notes |
|---|---|---|---|
| T1 (8) | T1.1 to T1.6, T1.8 | **T1.7** | The fix candidate restored calibration but more than tripled wrong city exposure |
| T2 (4) | T2.1, T2.2, T2.4 | **T2.3** | Hole strata resolve 34%, mostly within 50 m via neighbouring records; my premise that every answer there is wrong was false |
| T4 (5) | T4.1, T4.3, T4.4 | **T4.2, T4.5** | Exact name keys rarely agree across sources (9.1%, predicted 30 to 70%); GeoNames larger than predicted |
| T6 (5) | T6.1, T6.5 | **T6.2, T6.3, T6.4** | Facing the nearest road is worse than the centroid; the footway end works but partly reads the label |

Full text, unchanged since it was committed before each run: `docs/PREDICTIONS.md`.

## Blocked or not done

- Second and third training seeds for T1 (compute). The T1 conclusion rests on one seed per model.
- A POI tier specific calibration map, the obvious fix that leaves the address model alone: not
  registered, not run.
- Merging Overture into the gazetteer: terms allow it, but it needs fuzzier name matching and an
  evaluation whose truth is not Overture itself.
- Accuracy of the Abu Dhabi regional model: not measured.
- Sealed evaluation of v2.1: deliberately not run (no sealed2 exists).

## What Huda must do next

See `docs/NEEDS_FROM_HUDA.md`: review and merge PR #1 when satisfied; send the Makani letter after
filling the contact fields; optionally create the release and Render blueprint for the demo;
start collecting the human written set.

## Single best next step

**Collect the human written set** (`bench/human_kit/`), at least 400 rows and ideally 1,000, held
back under the `docs/SEALED2.md` rules. It is the only source of fresh held out data, it replaces
synthetic queries with real ones, and every other claim in this repository waits on it.
