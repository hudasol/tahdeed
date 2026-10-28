"""Render docs/BENCH_REPORT.md from bench/data/MANIFEST.json and bench/results/*.score.json.

Every number in the generated tables comes from those files; the prose around them is static.
"""

from __future__ import annotations

import json
from pathlib import Path

SYSTEMS = [
    ("naive", "Naive fuzzy (rapidfuzz token-set, house-number shortlist)"),
    ("tfidf", "TF-IDF char 3-4gram nearest neighbour (address + POI strings)"),
    ("bm25", "BM25 (address + POI strings)"),
    ("nominatim", "Public Nominatim (sample, ≤1 req/s)"),
    ("photon", "Public Photon (sample, ≤1 req/s)"),
    ("tahdeed", "Tahdeed"),
]
SAMPLED = {"nominatim", "photon"}  # rate limited systems: scored on their own sample
HEADLINE_SETS = ["address_dev", "address_sealed", "hole_dev", "hole_sealed", "poi_dev",
                 "poi_sealed", "landmark_dev", "gold_handwritten"]  # fmt: skip


_HEAD = "| System | n | Answered | Precision@50 m | Wrong city | End-to-end@50 m | Forced@1 km |"
_SEP = "|---|---|---|---|---|---|---|"


def _row(label: str, o) -> str:
    if o is None:
        return f"| {label} | – | – | – | – | – | – |"
    return (f"| {label} | {o['n']} | {_p(o['answered'])} | {_p(o['precision_50m'])} | "
            f"{_p(o['confident_wrong_city'])} | {_p(o['end_to_end_50m'])} | {_p(o['forced_1km'])} |")  # fmt: skip


def _p(x) -> str:
    return "–" if x is None else f"{100 * x[0]:.1f} ({100 * x[1]:.0f}–{100 * x[2]:.0f})"


_EXT_HEAD = (
    "| System | n | Answered | Precision@50 m | Wrong city | End-to-end@50 m | Forced@1 km | ECE |"
)
_EXT_SEP = "|---|---|---|---|---|---|---|---|"


def _ext_row(label: str, o) -> str:
    if o is None:
        return f"| {label} | – | – | – | – | – | – | – |"
    ece = "–" if o.get("ece_conf_50m") is None else f"{o['ece_conf_50m']:.3f}"
    return (f"| {label} | {o['n']} | {_p(o['answered'])} | {_p(o['precision_50m'])} | "
            f"{_p(o['confident_wrong_city'])} | {_p(o['end_to_end_50m'])} | {_p(o['forced_1km'])} | {ece} |")  # fmt: skip


def _load(f: Path):
    return json.loads(f.read_text()) if f.exists() else None


def _external(results: Path, data: Path) -> list[str]:
    """Baseline tables for the OpenStreetMap independent sets, from score files only."""
    mp = data / "MANIFEST.json"
    if not mp.exists():
        return []
    man = json.loads(mp.read_text())
    L = ["## Independent real text sets (not OpenStreetMap)", "",
         "These two sets are written by businesses (Overture Maps Places) or by Wikidata editors. They are not "
         "generated from OpenStreetMap, they are not synthetic, and they are not driver direction text. The truth is "
         "the source's own coordinate and can be wrong, so absolute numbers carry that noise. Neither set was seen "
         "or used for tuning by the developers (see the pre-registration in `docs/PREDICTIONS.md`, section G). "
         "Licences: see `bench/data_external/NOTICE.md`; the files are kept apart from the ODbL files.",
         "", "| Set | n | Source | Strata | Contamination | sha256 (head) |", "|---|---|---|---|---|---|"]  # fmt: skip
    for s, m in man["sets"].items():
        src = (
            f"release {m['release']}"
            if m.get("release")
            else f"retrieved {m.get('retrieved', '?')}"
        )
        strata = ", ".join(f"{k}: {v}" for k, v in m.get("strata", {}).items())
        L.append(
            f"| {s} | {m['n']} | {src} | {strata} | {m['contamination']} | `{m['sha256'][:10]}` |"
        )
    L += ["", "Cells are percent with Wilson 95% interval, as above; *ECE* is the expected calibration error of the "
          "system's own confidence against the within 50 m indicator (only Tahdeed reports a confidence). The index "
          "baselines (TF-IDF, BM25) always answer and return a gazetteer record, so their *Answered* is 100% by "
          "construction and *Precision* equals *End-to-end*. libpostal could not be installed in the build "
          "environment (see `bench/README.md`) and has no row.", ""]  # fmt: skip
    scores = {k: _load(results / f"{k}.score.json") for k, _ in SYSTEMS}
    scores = {k: v for k, v in scores.items() if v}
    for s in man["sets"]:
        if not any(s in sc["sets"] for sc in scores.values()):
            continue
        L += [
            f"### {s}",
            "",
            "All rows (systems that were run on every row).",
            "",
            _EXT_HEAD,
            _EXT_SEP,
        ]
        for k, label in SYSTEMS:
            if k in SAMPLED or k not in scores:
                continue
            L.append(_ext_row(label, scores[k]["sets"].get(s, {}).get("overall")))
        L += ["", "Like-for-like on the public geocoder sample (identical ids for every system).", "",
              _EXT_HEAD, _EXT_SEP]  # fmt: skip
        for k, label in SYSTEMS:
            f = results / (f"{k}.score.json" if k in SAMPLED else f"{k}.sample.score.json")
            sc = _load(f)
            if sc:
                L.append(_ext_row(label, sc["sets"].get(s, {}).get("overall")))
        strata = {k: v["sets"][s]["strata"] for k, v in scores.items()
                  if k not in SAMPLED and s in v["sets"] and v["sets"][s]["strata"]}  # fmt: skip
        if strata:
            L += ["", "Per stratum, all rows.", "",
                  "| Stratum | System | n | Answered | Precision@50 m | End-to-end@50 m |", "|---|---|---|---|---|---|"]  # fmt: skip
            names = sorted({st for d in strata.values() for st in d})
            for st in names:
                for k, label in SYSTEMS:
                    o = strata.get(k, {}).get(st)
                    if o:
                        L.append(f"| {st} | {label} | {o['n']} | {_p(o['answered'])} | "
                                 f"{_p(o['precision_50m'])} | {_p(o['end_to_end_50m'])} |")  # fmt: skip
        L.append("")
    return L


def render(
    results: Path, data: Path, ext_results: Path | None = None, ext_data: Path | None = None
) -> str:
    """The report. The external (OpenStreetMap independent) section is added when
    ``<data>/../data_external`` and ``<results>/../results_external`` exist, unless given."""
    man = json.loads((data / "MANIFEST.json").read_text())
    ext_data = ext_data or data.parent / "data_external"
    ext_results = ext_results or results.parent / "results_external"
    scores = {}
    for k, _ in SYSTEMS:
        f = results / f"{k}.score.json"
        if f.exists():
            scores[k] = json.loads(f.read_text())
    L = ["<!-- GENERATED by `tahdeed bench report` from bench/results/*.score.json; do not edit. -->",
         "# Gulf-AddressBench report", "",
         f"Benchmark version {man['version']}; gazetteer SHA-256 `{man['gazetteer_sha256'][:16]}…`. "
         "See [bench/README.md](../bench/README.md) for the task, [bench/DATA_CARD.md](../bench/DATA_CARD.md) "
         "for construction, licences and the contamination table.", ""]  # fmt: skip
    L += [
        "## Sets",
        "",
        "| Set | n | Generator | Split | Contamination | sha256 (head) |",
        "|---|---|---|---|---|---|",
    ]
    for s, m in man["sets"].items():
        L.append(
            f"| {s} | {m['n']} | {m['generator']} | {m['split']} | {m['contamination']} | `{m['sha256'][:10]}` |"
        )
    L += ["", "## Headline results", "",
          "Cells are percent with Wilson 95% interval (low–high). *Answered* = the system gave a "
          "non-abstaining location. *Precision* = within 50 m among answered. *Wrong city* = answered "
          "city differs from truth city, among answered. *End-to-end* counts abstentions as misses. "
          "`–` = system not run on that set.", ""]  # fmt: skip
    for s in HEADLINE_SETS:
        if not any(s in sc["sets"] for sc in scores.values()):
            continue
        L += [f"### {s}", "", "| System | n | Answered | Precision@50 m | Wrong city | End-to-end@50 m | Forced@1 km |",
              "|---|---|---|---|---|---|---|"]  # fmt: skip
        for k, label in SYSTEMS:
            o = scores.get(k, {}).get("sets", {}).get(s, {}).get("overall")
            if o is None:
                L.append(f"| {label} | – | – | – | – | – | – |")
            else:
                L.append(f"| {label} | {o['n']} | {_p(o['answered'])} | {_p(o['precision_50m'])} | "
                         f"{_p(o['confident_wrong_city'])} | {_p(o['end_to_end_50m'])} | {_p(o['forced_1km'])} |")  # fmt: skip
        L.append("")
    nom = scores.get("nominatim")
    if nom:
        L += ["### Like-for-like on the Nominatim sample", "",
              "Public Nominatim and Photon were queried at ≤1 request/s on an even-stride sample of each set (hole rows "
              "excluded: a global geocoder cannot have a record removed). The other systems are re-scored on exactly the "
              "same ids (`*.sample.score.json`); Photon was asked for the same ids as Nominatim. Both public services "
              "are competitors, never ground truth.", ""]  # fmt: skip
        for s in nom["sets"]:
            L += [f"**{s}**", "", _HEAD, _SEP]
            for k, label in SYSTEMS:
                f = results / (f"{k}.score.json" if k in SAMPLED else f"{k}.sample.score.json")
                o = (
                    json.loads(f.read_text())["sets"].get(s, {}).get("overall")
                    if f.exists()
                    else None
                )
                L.append(_row(label, o))
            L.append("")
    for s in ("crosscity_dev", "crosscity_sealed"):
        for k, label in SYSTEMS:
            sub = scores.get(k, {}).get("sets", {}).get(s)
            if not sub or not sub["strata"]:
                continue
            L += [f"### {s}: {label}", "",
                  "Strata are (stratum/evidence): E0 = street + number only, E1 = + district, E2 = + city.", "",
                  "| Stratum | n | Answered | Wrong city (of answered) | End-to-end@50 m |", "|---|---|---|---|---|"]  # fmt: skip
            for st, o in sub["strata"].items():
                L.append(
                    f"| {st} | {o['n']} | {_p(o['answered'])} | {_p(o['confident_wrong_city'])} | {_p(o['end_to_end_50m'])} |"
                )
            L.append("")
    L += _external(ext_results, ext_data)
    L += ["## Reading the results", "",
          "- **Abstention changes what a table means.** Tahdeed answers fewer queries and is right far more often "
          "when it does; the naive baseline answers almost everything and is mostly wrong. Compare *precision* and "
          "*end-to-end* together, never one alone.",
          "- **Nominatim** is a general geocoder queried with synthetic text that is garbled on purpose (transliteration "
          "variants, typos). It answers few of those, and is competitive or ahead on clean-ish POI and cross-city text, where it "
          "has the whole current OSM including the truth record. It is not a like-for-like opponent on hole sets (it cannot "
          "have a record removed), so those rows are blank. Its sample is small (n=100 per set); intervals are wide.",
          "- **Cross-city**: with no city given, Nominatim often answers (and is sometimes wrong city); Tahdeed's city gate "
          "asks instead, which costs end-to-end score on this set by design. See `docs/EVALUATION.md` for the exposure/coverage trade-off.",
          "", "## Limitations", "",
          "1. OpenStreetMap is both the truth and the data the baselines index; \"within 50 m\" is relative to OSM.",
          "2. All sets in `bench/data` except `gold_handwritten` are synthetic; generated noise is not how people write. "
          "The two independent sets above are not synthetic, but their truth is a source's own coordinate; the driver-direction human set is pending.",
          "3. Dev-seen sets are optimistic for Tahdeed (see the contamination column); the sealed sets are the fair ones, and `crosscity_sealed` was used once.",
          "4. The gold set has 40 rows and was used while building the system.",
          "5. Cross-city set composition is chosen to expose a failure: rates are not prevalence estimates.",
          "6. Coverage is concentrated in Abu Dhabi emirate (about 85% of structured addresses); no per-emirate claims are made.",
          ""]  # fmt: skip
    L += ["### human_v1", "", "**Pending real data.** No volunteer data has been collected; this set is "
          "intentionally empty. See [bench/human_kit/README.md](../bench/human_kit/README.md). "
          "Numbers will appear here only from `tahdeed human evaluate` on real responses.", ""]  # fmt: skip
    return "\n".join(L)
