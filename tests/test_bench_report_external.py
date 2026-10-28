"""The report grows an external section only from files on disk, and its numbers come from scores."""

import json
from pathlib import Path

from tahdeed import bench
from tahdeed import bench_external as be
from tahdeed.bench_report import render


def _rec(i):
    return {"id": i, "name": f"Cafe {i}", "address": "Ground Floor, Dubai Mall, Financial Centre Road",
            "category": "cafe", "confidence": 0.9, "operating_status": None,
            "lat": 25.1972, "lon": 55.2744,
            "sources": [{"dataset": "meta", "license": "CDLA-Permissive-2.0"}]}  # fmt: skip


def test_report_gets_an_external_section_only_from_score_files(tmp_path: Path):
    main = tmp_path / "bench" / "data"
    main.mkdir(parents=True)
    (main / "MANIFEST.json").write_text(
        json.dumps({"version": "1.0.0", "gazetteer_sha256": "0" * 64, "sets": {}})
    )
    (tmp_path / "bench" / "results").mkdir()
    assert "Independent real text sets" not in render(tmp_path / "bench" / "results", main)

    ext, res = tmp_path / "bench" / "data_external", tmp_path / "bench" / "results_external"
    rows = be.sample_overture([_rec(f"x{i}") for i in range(5)], {"dubai": 5}, seed=3)
    sha = be._write_set(ext, "overture_places", rows)
    be._update_manifest(
        ext,
        "overture_places",
        {
            "n": 5,
            "sha256": sha,
            "release": "r",
            "contamination": "never seen by developers",
            "strata": {"dubai": 5},
        },  # fmt: skip
    )
    res.mkdir()
    pred = res / "tahdeed.pred.jsonl"
    pred.write_text(
        "\n".join(json.dumps({"id": r["id"], "lat": r["lat"], "lon": r["lon"]}) for r in rows)
    )
    (res / "tahdeed.score.json").write_text(json.dumps(bench.score(pred, ext)))
    md = render(tmp_path / "bench" / "results", main)
    assert "## Independent real text sets" in md and "### overture_places" in md
    assert "| Tahdeed | 5 | 100.0 (57–100) |" in md  # a number that comes from the score file
    assert "never seen by developers" in md
