"""The CI drift check passes on the committed files and fails when a score file is edited."""

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drift", ROOT / "scripts" / "check_bench_drift.py")
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)


def _copy_naive(tmp: Path) -> Path:
    res = tmp / "results"
    res.mkdir()
    for f in ("naive.pred.jsonl", "naive.score.json"):
        shutil.copy(ROOT / "bench" / "results" / f, res / f)
    return res


def test_committed_naive_results_reproduce(tmp_path):
    assert drift.check(results=_copy_naive(tmp_path)) == []


def test_hand_edited_score_is_detected(tmp_path):
    res = _copy_naive(tmp_path)
    p = res / "naive.score.json"
    d = json.loads(p.read_text())
    s = next(iter(d["sets"].values()))
    s["overall"]["answered"][0] += 0.001
    p.write_text(json.dumps(d))
    problems = drift.check(results=res)
    assert problems and "answered" in problems[0]


def test_edited_dataset_is_detected(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(ROOT / "bench" / "data", data)
    f = data / "gold_handwritten.jsonl"
    f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    problems = drift.check(data=data, results=tmp_path / "none")
    assert any("gold_handwritten.jsonl" in p for p in problems)
