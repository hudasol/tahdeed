"""Fill the generated result blocks in README.md and docs/MODEL_CARD.md from the result JSON.

Blocks sit between `<!-- RESULTS:name BEGIN -->` and `<!-- RESULTS:name END -->`; nothing inside is
hand-written. Run after the eval / crosscity / bench jobs (scripts/reproduce.sh does).
"""

import json
import re
from pathlib import Path

R = Path(__file__).resolve().parents[1]
L = lambda p: json.loads((R / p).read_text())  # noqa: E731
pc = lambda x: f"{100 * x:.1f}%"  # noqa: E731
ci = lambda d: f"{100 * d['rate']:.1f}% ({100 * d['ci95'][0]:.1f}-{100 * d['ci95'][1]:.1f})"  # noqa: E731


def blocks() -> dict[str, str]:
    dev, sealed20 = L("docs/eval.json"), L("docs/sealed/eval.json")
    ccd, ccs = L("docs/crosscity_dev.json"), L("docs/crosscity_sealed.json")
    a, h, p = (dev[k] for k in ("abu_dhabi_structured", "coverage_hole", "dubai_poi"))
    sd = ccd["configs"]["gate_0.35"]["standard"]
    ss = ccs["configs"]["gate_0.35"]["standard"]
    ss0 = ccs["configs"]["baseline_v2.0"]["standard"]

    def risk(cc, cfg):
        c = cc["configs"][cfg]["cells"]
        return c["risk/E0"], c["named_unique/E0"], c["risk/E2"]

    rows = [
        "| | dev (model trained from the current code) | sealed (earlier model, not rerun) |",
        "|---|---|---|",
        f"| Standard benchmark: answers it is confident about | {pc(sd['resolved_coverage'])} | {pc(ss['resolved_coverage'])} |",
        f"| ...of those, within 50 m | **{pc(sd['resolved_precision_50m'])}** | **{pc(ss['resolved_precision_50m'])}** |",
        f"| Forced top-1 within 50 m | {pc(sd['forced_top1_50m'])} | {pc(ss['forced_top1_50m'])} |",
        f"| ECE of P(within 50 m) | {sd['ece_p50']:.3f} | {ss['ece_p50']:.3f} |",
    ]
    for lab, cfg in (
        ("no city gate (v2.0 behaviour)", "baseline_v2.0"),
        ("city gate on (default)", "gate_0.35"),
    ):
        rk = {k: risk(ccd, cfg) for k in ("d",)}["d"]
        rs = risk(ccs, cfg)
        rows.append(
            f"| **Wrong-city answers, % of cross-city risk queries with no city given** ({lab}) | {ci(rk[0]['wrong_city_of_all'])} | {ci(rs[0]['wrong_city_of_all'])} |"
        )
    rk, rs = risk(ccd, "gate_0.35"), risk(ccs, "gate_0.35")
    rows += [
        f"| ...cost: answered share of those queries | {ci(rk[0]['coverage'])} | {ci(rs[0]['coverage'])} |",
        f'| ...cost: asked "which city?" on unique names (E0) | {pc(rk[1]["asked_city"]["rate"])} | {pc(rs[1]["asked_city"]["rate"])} |',
        f"| ...with the city written (E2), wrong-city rate of answers | {ci(rk[2]['confident_wrong_city'])} | {ci(rs[2]['confident_wrong_city'])} |",
        f"| True address missing from the index: precision of confident answers | {pc(h['resolved_precision_50m'])} | not re-run |",
        f"| Dubai/Sharjah/Ajman POI queries: answered / ECE | {pc(p['resolved_coverage'])} / {p['ece_p50']:.3f} | not re-run |",
        f"| Latency (median, one core) | {a['latency_ms_p50']:.1f} ms | |",
    ]
    results = "\n".join(rows)
    results += (
        "\n\nCross-city rows use the synthetic `crosscity` set (pairs of the same record with and without district/city "
        "evidence; composition chosen to expose the failure, **not** a prevalence estimate). The standard-benchmark "
        f"coverage without the gate was {pc(ss0['resolved_coverage'])} on sealed. "
        "Frozen v2.0 release, sealed, for reference: "
        f"{pc(sealed20['abu_dhabi_structured']['resolved_coverage'])} answered, "
        f"{pc(sealed20['abu_dhabi_structured']['resolved_precision_50m'])} within 50 m."
    )
    short = (
        f"Standard benchmark, sealed (earlier model, not rerun): {pc(ss['resolved_coverage'])} answered, "
        f"{pc(ss['resolved_precision_50m'])} of those within 50 m. Cross-city risk queries with no city given: "
        f"wrong-city answers {ci(risk(ccs, 'baseline_v2.0')[0]['wrong_city_of_all'])} without the gate, "
        f"{ci(risk(ccs, 'gate_0.35')[0]['wrong_city_of_all'])} with it. "
        f"True address missing (dev): {pc(h['resolved_precision_50m'])} of confident answers right. "
        f"Dubai/Sharjah/Ajman POI calibration (dev) ECE {p['ece_p50']:.3f} (was 0.069 on v2.0: a regression, see EVALUATION.md)."
    )
    return {"results": results, "model_card": short, "real_text": real_text()}


def real_text() -> str:
    """Independent real text sets (bench/data_external): Tahdeed against the public baselines."""
    systems = (
        ("Tahdeed", "tahdeed"),
        ("TF-IDF nearest neighbour", "tfidf"),
        ("BM25", "bm25"),
        ("Photon (150 row sample)", "photon"),
        ("Nominatim (150 row sample)", "nominatim"),
    )
    rows = [
        "| Set | System | n | Answered | Within 50 m, of answered | Wrong city, of answered | Within 50 m, of all |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in ("overture_places", "wikidata_addresses"):
        for label, key in systems:
            f = R / "bench" / "results_external" / f"{key}.score.json"
            if not f.exists():
                continue
            o = json.loads(f.read_text())["sets"].get(name, {}).get("overall")
            if not o:
                continue

            def c(m, o=o):
                v = o[m]
                return f"{100 * v[0]:.1f}% ({100 * v[1]:.0f}-{100 * v[2]:.0f})"

            rows.append(
                f"| {name} | {label} | {o['n']} | {c('answered')} | {c('precision_50m')} | "
                f"{c('confident_wrong_city')} | {c('end_to_end_50m')} |"
            )
    return "\n".join(rows)


def fill(path: Path, name: str, text: str) -> None:
    s = path.read_text()
    pat = re.compile(rf"(<!-- RESULTS:{name} BEGIN -->\n).*?(\n<!-- RESULTS:{name} END -->)", re.S)
    if not pat.search(s):
        raise SystemExit(f"{path}: markers for {name} missing")
    path.write_text(pat.sub(lambda m: m.group(1) + text + m.group(2), s))


if __name__ == "__main__":
    b = blocks()
    fill(R / "README.md", "results", b["results"])
    fill(R / "README.md", "real_text", b["real_text"])
    fill(R / "docs" / "MODEL_CARD.md", "model_card", b["model_card"])
    print("updated README.md and docs/MODEL_CARD.md")
