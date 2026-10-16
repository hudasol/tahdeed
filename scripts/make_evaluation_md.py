"""Regenerate docs/EVALUATION.md from the result files (no hand-copied numbers)."""

import json
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "docs"
load = lambda p: json.loads((D / p).read_text())  # noqa: E731
ev, sev = load("eval.json"), load("sealed/eval.json")
st, sst = load("studies.json"), load("sealed/studies.json")
gold = load("gold.json")
pc = lambda x: f"{100 * x:.1f}%"  # noqa: E731
BM = [
    ("abu_dhabi_structured", "Abu Dhabi / Al Ain / Al Dhafra, held-out districts"),
    ("coverage_hole", "Same, true address removed from the index"),
    ("dubai_poi", "Dubai / Sharjah / Ajman POI (weaker truth)"),
]


def headline(e):
    rows = [
        "| Benchmark | n | resolved | precision@50 m of resolved | top-1 ≤50 m (forced) | ≤1 km | ECE P(≤50 m) | median ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k, name in BM:
        b = e[k]
        rows.append(
            f"| {name} | {b['n']} | {pc(b['resolved_coverage'])} | **{pc(b['resolved_precision_50m'])}** | {pc(b['forced_top1_50m'])} | {pc(b['forced_top1_1km'])} | {b['ece_p50']:.3f} | {b['latency_ms_p50']:.1f} |"
        )
    return "\n".join(rows)


def holes(e):
    rows = [
        "| Share of queries whose true address is absent | resolved | precision@50 m of resolved | forced top-1 ≤50 m | ECE P(≤50 m) |",
        "|---|---|---|---|---|",
    ]
    for k, v in sorted(e["hole_sensitivity"].items(), key=lambda kv: float(kv[0])):
        rows.append(
            f"| {float(k):.0%} | {pc(v['resolved_coverage'])} | {pc(v['resolved_precision_50m'])} | {pc(v['forced_top1_50m'])} | {v['ece_p50']:.3f} |"
        )
    return "\n".join(rows)


def gap(s):
    g = s["generator_gap"]
    rows = [
        "| Query generator | forced top-1 ≤50 m | resolved | precision of resolved | ECE P(≤50 m) |",
        "|---|---|---|---|---|",
    ]
    for k, name in (
        ("v1_english_perturbed", "v1: English names perturbed (the training generator)"),
        ("v2_from_arabic", "v2: Latin text produced from the Arabic names (independent)"),
    ):
        v = g[k]
        rows.append(
            f"| {name} | {pc(v['forced_top1_50m'])} | {pc(v['resolved_coverage'])} | {pc(v['resolved_precision_50m'])} | {v['ece_p50']:.3f} |"
        )
    for k, v in s["v2_by_style"].items():
        rows.append(
            f"| &nbsp;&nbsp;v2 style `{k.replace('style_', '')}` (n={v['n']}) | {pc(v['forced_top1_50m'])} | {pc(v['resolved_share'])} | {pc(v['resolved_precision'])} | {v['ece_p50']:.3f} |"
        )
    return "\n".join(rows)


def abl(s):
    a = s["ablations"]
    rows = [
        f"| Configuration (n={a['n']}, 30% holes, v1+v2 mix) | forced top-1 ≤50 m | Δ vs full (95% paired CI) | precision of resolved | ECE |",
        "|---|---|---|---|---|",
    ]
    for name, r in a["rows"].items():
        d = r.get("top1_vs_full")
        dd = (
            "-"
            if not d
            else f"{100 * d['diff']:+.1f} ({100 * d['ci95'][0]:+.1f}..{100 * d['ci95'][1]:+.1f}){'' if d['significant'] else ' ns'}"
        )
        rows.append(
            f"| {name} | {pc(r['forced_top1_50m'])} | {dd} | {pc(r['resolved_precision'])} | {r['ece_p50']:.3f} |"
        )
    t = s["baseline_tfidf_char34"]
    rows.append(
        f"| Baseline: char 3-4-gram TF-IDF nearest neighbour | {pc(t['forced_top1_50m'])} | {100 * t['vs_full']['diff']:+.1f} ({100 * t['vs_full']['ci95'][0]:+.1f}..{100 * t['vs_full']['ci95'][1]:+.1f}) | - | - |"
    )
    return "\n".join(rows)


def lm(s):
    l = s["landmark"]
    return f"{pc(l['top1_within_200m'])} within 200 m of the landmark with the landmark tier, {pc(l['top1_within_200m_without'])} without (n={l['n']})"


def crosscity_tbl(cc):
    ci = lambda d: f"{100 * d['rate']:.1f}% ({100 * d['ci95'][0]:.1f}-{100 * d['ci95'][1]:.1f})"  # noqa: E731
    rows = [
        "| Config | std resolved | std precision | risk E0: answered | risk E0: **wrong city, % of all** | risk E0: asked city | unique E0: answered | unique E0: asked | risk E1: wrong city | risk E2: wrong city |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k, v in cc["configs"].items():
        c, sd = v["cells"], v["standard"]
        r0, u0 = c["risk/E0"], c["named_unique/E0"]
        r1 = c.get("risk/E1")
        r2 = c["risk/E2"]
        rows.append(
            f"| {k} | {pc(sd['resolved_coverage'])} | {pc(sd['resolved_precision_50m'])} | {ci(r0['coverage'])} | {ci(r0['wrong_city_of_all'])} | {pc(r0['asked_city']['rate'])} | {pc(u0['coverage']['rate'])} | {pc(u0['asked_city']['rate'])} | {ci(r1['wrong_city_of_all']) if r1 else '-'} | {ci(r2['wrong_city_of_all'])} |"
        )
    return "\n".join(rows)


def maybe(p):
    return load(p) if (D / p).exists() else None


def ci_(d):
    return f"{100 * d['rate']:.1f}% ({100 * d['ci95'][0]:.1f}-{100 * d['ci95'][1]:.1f})"


POI_MODELS = [
    ("M21", "v2.1 as published (features + cross-city mix)"),
    ("M20", "v2.0 training (no features, no mix)"),
    ("M_nofeat", "(a) mix, features masked"),
    ("M_nomix", "(b) features, no mix"),
    ("M_nopoihole", "fix candidate: mix without `poi_hole` rows"),
]


def poi_ablation(pa):
    m = pa["models"]
    rows = [
        "| Model | POI ECE, shipped (95% bootstrap) | POI ECE, gate off | POI ECE, v2.0 flags | POI answered, shipped | POI answered, gate off | risk E0 wrong city, % of all (gate 0.35) | std resolved / precision (gate 0.35) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k, name in POI_MODELS:
        if k not in m:
            continue
        p, cc = m[k]["poi"], m[k]["crosscity"]["gate_0.35"]
        lo, hi = p["shipped"]["ece_p50_ci95"]
        rows.append(
            f"| {k}: {name} | {p['shipped']['ece_p50']:.3f} ({lo:.3f}-{hi:.3f}) | {p['gate_off']['ece_p50']:.3f} | {p['v20_flags']['ece_p50']:.3f} | {pc(p['shipped']['resolved_coverage'])} | {pc(p['gate_off']['resolved_coverage'])} | {ci_(cc['risk_E0']['wrong_city_of_all'])} | {pc(cc['standard']['resolved_coverage'])} / {pc(cc['standard']['resolved_precision_50m'])} |"
        )
    return "\n".join(rows)


def poi_section(pa):
    if pa is None:
        return "Not run yet."
    return f"""Dev split only, every model retrained on the **2026-10-15** OSM extract (gazetteer
`{pa["gazetteer_sha256"][:12]}`; the published v2.0 and v2.1 numbers elsewhere in this document used
the 2026-10-09 extract, which the mirror no longer offers). One training seed per model. POI
benchmark n={pa["n_poi"]}. Source: `docs/poi_ablation.json`; predictions T1.1 to T1.8 in
[`PREDICTIONS.md`](PREDICTIONS.md).

{poi_ablation(pa)}

Reading: ECE does not move with the gate or with diversification; it moves with the training mix.
Removing the cross-city mix (or only its `poi_hole` rows) restores v2.0 POI calibration, but the
same rows are what keep the model cautious about street names shared across cities, so address
wrong-city exposure roughly triples. Under the rule fixed before the run, no candidate qualified
and the published v2.1 model is kept. **Trade-off, stated plainly: better Dubai POI calibration
currently costs about three times the wrong-city exposure on the address risk set.**"""


def clarify_sec(c):
    if c is None:
        return "Not run yet."
    rows = [
        '| Group | E0 queries | asked "Which city?" | with the true city: resolved within 50 m | resolved beyond 50 m | resolved in another city | same status as E2 |',
        "|---|---|---|---|---|---|---|",
    ]
    for k in ("non_hole", "hole"):
        g = c["groups"][k]
        rows.append(
            f"| {k.replace('_', ' ')} | {g['n_e0']} | {ci_(g['asked_city'])} | {ci_(g['hint_resolved_within50'])} | {ci_(g['hint_resolved_beyond50'])} | {ci_(g['hint_resolved_wrong_city'])} | {ci_(g['same_status_as_E2'])} |"
        )
    return "\n".join(rows)


def supp_sec(s):
    if s is None:
        return "Not run yet."
    o, t, g = s["overture"], s["osm_dev_dubai_poi_pool"], s["geonames"]
    med = t["median_m_of_matched"]
    match = (
        f"{ci_(t['overture_same_key_within_100m'])}, median {med:.0f} m"
        if med is not None
        else "none"
    )
    return "\n".join(
        [
            "| Measure | Value |",
            "|---|---|",
            f"| Overture Places rows in the Dubai bbox | {o['rows_in_bbox']} |",
            f"| ...with only CDLA Permissive 2.0 / Apache 2.0 / CC0 source licences | {ci_(o['rows_only_permissive_licences'])} |",
            f"| OSM dev Dubai POIs (n={t['n']}) with an Overture place of the same name key within 100 m | {match} |",
            f"| Overture places with confidence at least 0.7 (n={o['confidence_ge_0_7']}) and no OSM POI of the same key within 500 m | {ci_(o['confident_without_osm_same_key_500m'])} |",
            f"| GeoNames feature class S rows in the bbox | {g['class_S_rows_in_bbox']} |",
            f"| ...without an OSM POI of the same key within 500 m | {g['without_osm_same_key_500m']} |",
        ]
    )


def lastmeter_sec(lmv):
    if lmv is None:
        return "Not run yet."
    rows = [
        f"n={lmv['n_labelled_buildings']} labelled buildings, {lmv['n_entrance_labels']} mapped entrances.",
        "",
        "| Proposer | within 5 m | within 10 m | within 20 m | median m (where proposed) | no proposal |",
        "|---|---|---|---|---|---|",
    ]
    for k, v in lmv["proposers"].items():
        med = "-" if v["median_m"] is None else f"{v['median_m']:.1f}"
        rows.append(
            f"| {k} | {ci_(v['within_5m_of_all'])} | {ci_(v['within_10m_of_all'])} | {ci_(v['within_20m_of_all'])} | {med} | {v['no_proposal']} |"
        )
    return "\n".join(rows)


pa = maybe("poi_ablation.json")
clar = maybe("clarify_dev.json")
supp = maybe("supplements_dubai.json")
lmev = maybe("lastmeter_eval.json")

ccd, ccs = load("crosscity_dev.json"), load("crosscity_sealed.json")

out = f"""# Evaluation

Generated by `scripts/make_evaluation_md.py` from `docs/eval.json`, `docs/studies.json`,
`docs/sealed/*.json` and `docs/gold.json`. Gazetteer: {ev["meta"]["source"]} built {ev["meta"]["built_at"]}.
Splits are by district hash (train 50% / calibration 20% / **dev 20%** / **sealed 10%**).
Dev was used while iterating; sealed was run **once**, after the predictions in
[`PREDICTIONS.md`](PREDICTIONS.md) were written.

## Cross-city answers (Phase 2)

A street or POI name that exists in several cities, written without the city, can be answered
confidently in the wrong one. The synthetic cross-city set pairs the same record at three evidence
levels (E0 street+number only, E1 + district, E2 + city) and over strata *collision* (same street and
number in several cities) and *hole* (the true record is missing while another city has the same
street and number). **Risk** = collision + hole pooled. This set is built to expose the failure; its
rates are not prevalence estimates. `std` = the standard benchmark (n=3000) run under the same flags.
Intervals are Wilson 95%. Predictions and their hits and misses: [`PREDICTIONS.md`](PREDICTIONS.md).

### Dev (all gate margins; 0.35 was chosen here)

{crosscity_tbl(ccd)}

### Sealed (run once; baseline, diversify-only and the chosen margin)

{crosscity_tbl(ccs)}

![tradeoff](figures/crosscity_tradeoff.svg)

Reading: with no city given, holes in the registry look identical to unique, present records, so
wrong-city exposure falls only by giving up answers (the gate asks "which city?"). Giving the district
(E1) or city (E2) removes almost all of it. The residual after the gate is mostly rival cities
that are invisible to the system.

## Dubai POI calibration: which v2.1 change caused the regression (Phase 2, T1)

{poi_section(pa)}

## Answering "Which city?" (Phase 2, T2)

Cross-city dev set, model M21 above, shipped flags. Every E0 query that came back with a
"Which city?" question is resolved again with the true city as the `city` hint. In hole strata the
true record is hidden, so any resolved answer there is wrong. Source: `docs/clarify_dev.json`.

{clarify_sec(clar)}

## Dubai POI supplements: Overture Places and GeoNames (Phase 2, T4)

**Mixed truth**: OSM, Overture and GeoNames are each someone's claim; agreement is not accuracy,
and a place found only in a supplement has no independent truth here. Nothing was merged into the
gazetteer. Source: `docs/supplements_dubai.json`.

{supp_sec(supp)}

## Last meter entrance proposals (EXPLORATORY, Phase 2, T6)

Exploratory, not a headline claim. Labels are OSM-mapped entrance vertices on building outlines in
the Abu Dhabi emirate (`entrance=*` or `door=*`), **not surveyed**. The query point is the outline
centroid and mapped entrances are hidden. Shares are over all labelled buildings (no proposal
counts as a miss), Wilson 95%. Source: `docs/lastmeter_eval.json`.

{lastmeter_sec(lmev)}

## Read this first

- Queries are **synthetic** (two generators, one independent of training) plus a 40-row hand-written set. No query comes from a real user. Absolute numbers are optimistic; relative comparisons and calibration are the findings.
- Ground truth is the OpenStreetMap point the query was written about.
- Dubai has almost no structured OSM addresses, so only Dubai/Sharjah/Ajman POI queries are evaluated there.
- The hand-written set was used to find one defect (interior street-type spans), so its score is no longer an untouched estimate.

## Headline: sealed split, frozen v2.0 release (model before Phase 2)

{headline(sev)}

## Headline: dev split (v2.1: city gate on, retrained)

{headline(ev)}

"Forced" counts the best candidate even where tahdeed would have abstained or given only an area. "Resolved" is the confident answer.

## When the true address is not in the registry (sealed)

{holes(sev)}

Calibration (ECE) stays low across the range but precision cannot: a registry hole produces a confident wrong neighbour. This is a limit of the data, which only an official registry fixes.

## Does it hold on queries we did not write? (sealed)

{gap(sst)}

## Which components earn their keep? (sealed; dev in `studies.json`)

{abl(sst)}

`ns` = interval spans zero. Dev-split ablations: see `docs/studies.json`.

## Landmark queries ("near X, city")

Sealed: {lm(sst)}. Dev: {lm(st)}. Truth is the landmark's own point, so this tests finding the landmark, not the offset that "near" implies.

## Hand-written gold set

{gold["n"]} queries written by a person; {gold["resolved"]} resolved, {gold["resolved_within_50m"]} of those within 50 m; forced top-1 ≤50 m {pc(gold["top1_within_50m"])}. Sampling uncertainty at n=40 is about ±13 points. See the caveat above.

## Known failures

- A street name that exists in several cities, written without the city, is still answered in the wrong city when the true record is missing from the registry (a hole looks like a unique, present record). The city gate lowers this at a coverage cost; the residual is shown in the cross-city section.
- v2.1 regression: Dubai/Sharjah/Ajman POI calibration (ECE of P(within 50 m)) is worse than v2.0 on dev, and POI answers are fewer because chain names now trigger the city question. Diagnosed (T1 section above): the cross-city training mix, mostly its `poi_hole` rows, causes the ECE rise; removing them would roughly triple address wrong-city exposure, so they are kept and the trade-off stands.
- Registry holes (above).
- Arabizi remains the weakest style.
- Interpolation (+10 points forced top-1) assumes house numbers increase along a street and is checked only against held-out OSM addresses.
"""
(D / "EVALUATION.md").write_text(out)
print(len(out))
