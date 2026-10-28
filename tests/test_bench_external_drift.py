"""The committed external data, predictions and scores follow from each other (CI drift check)."""

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drift", ROOT / "scripts" / "check_bench_drift.py")
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)

EXT_DATA = ROOT / "bench" / "data_external"
EXT_RESULTS = ROOT / "bench" / "results_external"


def test_committed_external_results_reproduce():
    assert drift.check(data=EXT_DATA, results=EXT_RESULTS) == []


def test_external_rows_are_not_synthetic_and_carry_a_licence():
    for f in EXT_DATA.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            assert r["synthetic"] is False and r["hole"] is False
            assert r["source_licenses"] and r["text_kind"] in {"business_written", "human_written"}
            assert r["truth_ref"].split("/")[0] in {"overture", "wikidata"}  # never an OSM element


def test_edited_external_dataset_is_detected(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(EXT_DATA, data)
    f = data / "wikidata_addresses.jsonl"
    f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert any(
        "wikidata_addresses.jsonl" in p for p in drift.check(data=data, results=tmp_path / "x")
    )
