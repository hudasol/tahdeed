import json

import pytest

from tahdeed import bench


def _rows(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    rows = [
        {"id": "t-0", "set": "t", "text": "a", "lat": 25.2, "lon": 55.27, "truth_city": "dubai",
         "truth_city_geo": "dubai", "hole": False, "stratum": "x", "evidence": None},
        {"id": "t-1", "set": "t", "text": "b", "lat": 25.2, "lon": 55.27, "truth_city": "dubai",
         "truth_city_geo": "dubai", "hole": False, "stratum": "x", "evidence": None},
        {"id": "t-2", "set": "t", "text": "c", "lat": 25.2, "lon": 55.27, "truth_city": "dubai",
         "truth_city_geo": "dubai", "hole": False, "stratum": "x", "evidence": None},
    ]  # fmt: skip
    (d / "t.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    return d


def _preds(tmp_path, lines):
    p = tmp_path / "p.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines))
    return p


def test_score_counts_abstain_wrong_city_and_forced(tmp_path):
    d = _rows(tmp_path)
    p = _preds(tmp_path, [
        {"id": "t-0", "lat": 25.2, "lon": 55.27, "confidence": 0.9},           # exact
        {"id": "t-1", "lat": 24.45, "lon": 54.37, "city": "abu dhabi"},        # confident, wrong city
        {"id": "t-2", "lat": 25.2, "lon": 55.27, "abstain": True},             # abstains, but right
    ])  # fmt: skip
    o = bench.score(p, d)["sets"]["t"]["overall"]
    assert o["n"] == 3
    assert o["answered"][0] == pytest.approx(2 / 3)
    assert o["precision_50m"][0] == pytest.approx(0.5)
    assert o["confident_wrong_city"][0] == pytest.approx(0.5)
    assert o["end_to_end_50m"][0] == pytest.approx(1 / 3)
    assert o["forced_50m"][0] == pytest.approx(2 / 3)


def test_missing_ids_are_abstentions_and_bad_files_rejected(tmp_path):
    d = _rows(tmp_path)
    res = bench.score(_preds(tmp_path, [{"id": "t-0", "lat": 25.2, "lon": 55.27}]), d)
    assert res["sets"]["t"]["missing_predictions"] == 2
    for bad in (
        [{"id": "nope", "lat": 1, "lon": 1}],
        [{"id": "t-0", "lat": 1, "lon": 1}, {"id": "t-0", "lat": 1, "lon": 1}],
        [{"id": "t-0", "lat": 99, "lon": 1}],
        [{"id": "t-0", "lat": 1, "lon": 1, "confidence": 2}],
        [{"id": "t-0", "lat": 1, "lon": 1, "abstain": "no"}],
    ):
        with pytest.raises(ValueError):
            bench.score(_preds(tmp_path, bad), d)


def test_geometric_city_fallback(tmp_path):
    d = _rows(tmp_path)
    o = bench.score(_preds(tmp_path, [{"id": "t-0", "lat": 24.45, "lon": 54.37}]), d)
    assert o["sets"]["t"]["overall"]["confident_wrong_city"][0] == 1.0


def test_build_report_and_baselines_on_fixture(tmp_path):
    from pathlib import Path

    from tahdeed.bench_report import render

    db = Path(__file__).parent / "fixtures" / "mini.sqlite"
    man = bench.build(str(db), tmp_path / "d")
    assert "gold_handwritten" in man["sets"] and man["sets"]["address_dev"]["n"] > 0
    rows = bench.load_rows(tmp_path / "d", ["gold_handwritten"])
    assert len(rows) == 40 and all(r["synthetic"] is False for r in rows)
    preds = bench.baseline_naive(rows, str(db))
    assert {p["id"] for p in preds} == {r["id"] for r in rows}
    out = tmp_path / "r"
    out.mkdir()
    p = tmp_path / "p.jsonl"
    bench._write_preds(preds, p)
    (out / "naive.score.json").write_text(json.dumps(bench.score(p, tmp_path / "d")))
    md = render(out, tmp_path / "d")
    assert "Gulf-AddressBench report" in md and "Pending real data" in md
