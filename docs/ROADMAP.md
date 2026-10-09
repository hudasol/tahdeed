# Roadmap: turning the honest limits into engineering work

This document starts from the limits listed in `docs/EVALUATION.md`, finds the **root cause** of each
one (measured on the v1.0 code, not guessed), proposes the target architecture, and sets out five
review rounds. Each round is a critique written from a specific engineering viewpoint, a checklist, an
upgrade, and a re-measurement. The review documents live in `docs/reviews/`.

## 1. Why the limits happen (diagnosed, not assumed)

Two diagnostic scripts were run on v1.0 (2,500 hole queries; 400 consonant-variant queries).

| # | Honest limit (v1.0) | Measured root cause | Class of problem | Fix direction |
|---|---|---|---|---|
| L1 | Synthetic queries; noise model is ours | One author wrote both the generator and the matcher, so the matcher is tuned to the generator's habits (we even built the generator's `consonant` table and the matcher's coarse classes from the same mental list). No real-user text exists in the repo. | Evaluation validity | Second, independent query generator built from *Arabic* names via real romanisation schemes plus Arabizi; hand-written realistic gold set; sealed test split; report generalisation gap between generators. |
| L2 | Truth = OSM; Dubai only on POI queries | OSM has ~no structured Dubai addresses. Cannot be fixed by modelling; only by data or by honest scoping. | Data coverage | Probe open sources (Overture, Dubai Pulse); keep Dubai evaluated separately and label what it is; never present POI success as address success. |
| L3 | Hole: 29% of confident answers are wrong neighbours | **Prior shift.** The ranker was trained with 15% hidden-truth queries, so it learned "same street + same house number is nearly always right". In holes it returns the *same street name in another district or city* (e.g. "Wadi 'Arqeeyah Street" 126 km away at p=0.96) and interpolations of 100-170 m scored as 0.5-1.0 "within 50 m". 223 of 330 wrong confident answers were same street, same number, wrong district. | Training distribution + missing features | Train on a hole mixture; add district-conflict, key-ambiguity and "number absent from this street" features; cap interpolation confidence; report hole-sensitivity as a curve, not one number. |
| L4 | Consonant transliteration is weakest (45%) | **Evidence loss and blocked retrieval.** (a) Keys shorter than 4 characters are excluded from the coarse and fuzzy indices, so "Al Fagr" (`fkr`) never finds "Al Fajr" (`fjr`). (b) Greedy span selection lets a short exact partial ("kalifa") block the fuzzy full-name span, so long names fragment. (c) Digraph classes (kh, sh, gh) are handled in the key but not in the retrieval index. | Retrieval recall | Generate coarse/fuzzy spans for all n-grams, allow exact-coarse for short keys, score spans by explained mass; feature for how ambiguous a key is. |
| L5 | Short skeleton collisions | Skeletons discard vowels, so three-consonant keys (`db`, `sdf`) collide across unrelated names. No feature tells the ranker how ambiguous a key is. | Information loss | Add key-ambiguity (number of distinct names sharing a key) and a surface-similarity feature on the unstripped string. |
| L6 | Radius is conditional on the place being right | The 90% radius was fit only on correct-at-tier answers, so it describes extent, not risk. A user reads "within 2.5 km" as a guarantee. | Misleading uncertainty | Replace with calibrated P(within 50 m / 200 m / 1 km) heads; keep the radius but label it conditional. |
| L7 | Predictions were not pre-registered | Development and evaluation shared test districts. | Process | Three-way split of the test districts: *dev* (iterate), *sealed* (touch only at v1 and at the end). Predictions written to `docs/PREDICTIONS.md` before each sealed run. |
| L8 | Operational: pickle model, 420 MB, 7 s load, 2 cores | pickle executes code on load; sklearn is needed at inference; gazetteer indices are Python dicts. | Reliability / security | Export trees to a JSON/NumPy format, drop sklearn at inference, checksums, version stamps. |

## 2. Target architecture

```
                                  ┌───────────────────────── EVALUATION PLANE ─────────────────────────┐
                                  │ noise-v1 (rules)   noise-v2 (Arabic→Latin schemes, Arabizi)         │
                                  │ hand-written gold set     splits: train | calib | dev | SEALED      │
                                  │ metrics: precision@resolved, ECE, risk–coverage, CIs, ablations     │
                                  └───────────────▲─────────────────────────────────────▲──────────────┘
                                                  │ labelled queries                     │ drift / calibration check
┌────────── DATA PLANE ───────────┐   ┌───────────┴───────────── RESOLUTION PLANE ──────┴──────────────────────────────┐
│ OSM extract (ODbL)              │   │                                                                                │
│ optional open sources           │   │  text ─► normalise ─► parse ─► name matcher ─► candidate generator ─► ranker  │─► policy ─► answer
│   (Overture, city open data)    │──►│   (Arabic/Latin,    (house no.,   (exact | coarse   (address, POI,      (GBM →    (resolved /   + explain
│ build ─► versioned gazetteer    │   │    digits, skeleton)  Makani,      | fuzzy; multi-   interpolated,      JSON,     approximate / + asks
│  (SQLite + checksum + provenance)│  │                       landmark)     view keys; key   landmark, street,   numpy,    ambiguous /
│                                 │   │                                     ambiguity stats)  area, city)        calibrated) unresolved)
└─────────────────────────────────┘   └───────────────────────────────────────────────────────────────────────────────┘
                                                                  │
                    ┌─────────────────────────────────────────────┴───────────────────────────────────┐
                    │ SERVING PLANE: FastAPI (/resolve, /resolve/batch) · CLI · dashboard · audit log │
                    │ registry adapters (Makani / Onwani / National Address) behind one interface      │
                    └──────────────────────────────────────────────────────────────────────────────────┘
```

Design rules that follow from the diagnosis:

1. **Evidence is never discarded silently.** Every lossy transform (vowel dropping, class merging) is
   paired with a feature that says how lossy it was (key length, ambiguity, match view).
2. **The ranker is trained on the distribution it will be deployed on.** Hole rate, language mix and
   noise are *parameters of the training mixture*, and sensitivity to them is reported.
3. **Two independent generators.** Anything tuned against generator A is judged on generator B.
4. **Abstention beats a confident wrong point.** Costs are explicit in the policy.
5. **Inference is dependency-light and verifiable**: no pickle, versioned artefacts, deterministic.

## 3. The review rounds

| Round | Reviewer lens | What they attack | Output |
|---|---|---|---|
| 1 | Google, ML + systems | evaluation validity, calibration under shift, retrieval recall, latency | `reviews/01-google.md` |
| 2 | Edge Group, reliability + security | determinism, supply chain, offline deploy, auditability, failure modes | `reviews/02-edge.md` |
| 3 | TII, scientific rigour | ablations, baselines, significance, independent generalisation, documentation | `reviews/03-tii.md` |
| 4 | ATRC, Arabic NLP + responsible AI | Arabic orthography and dialect, Arabizi, landmark-style addresses, privacy | `reviews/04-atrc.md` |
| 5 | Senior specialist | everything left; polish plan | `reviews/05-senior.md` |

Every round ends with `tahdeed eval` on the *dev* split and a commit. The sealed split is evaluated
twice in total: once for v1.0 (already done, via the old test set), once at the end.
