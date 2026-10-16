"""Fail if the committed Gulf-AddressBench results no longer follow from the committed files.

    python scripts/check_bench_drift.py

Checks, with no gazetteer and no model needed:

1. every ``bench/data/*.jsonl`` matches the SHA-256 and row count in ``MANIFEST.json``;
2. re-scoring each committed prediction file (``bench/results/<system>.pred.jsonl``) reproduces
   its committed score file (``<system>.score.json``), and the like-for-like sample scores
   (``<system>.sample.score.json``, scored on the ids of Nominatim's sample) as well;
3. ``docs/BENCH_REPORT.md`` is exactly what ``tahdeed bench report`` renders from those files.

Any difference (data edited, scorer changed, results edited by hand) exits with status 1.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

from tahdeed.bench import DATA, RESULTS, ROOT, read_predictions, score
from tahdeed.bench_report import render

TOL = 1e-9
SAMPLED = {"nominatim"}


def _diff(a, b, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: present in only one file")
            else:
                out += _diff(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [
            d
            for i, (x, y) in enumerate(zip(a, b, strict=True))
            for d in _diff(x, y, f"{path}[{i}]")
        ]
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return [] if a is b else [f"{path}: {a} != {b}"]
        if math.isnan(a) and math.isnan(b):
            return []
        return [] if abs(a - b) <= TOL else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def check(data: Path = DATA, results: Path = RESULTS, report: Path | None = None) -> list[str]:
    problems: list[str] = []
    man = json.loads((data / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, meta in man["sets"].items():
        f = data / f"{name}.jsonl"
        if not f.exists():
            problems.append(f"{f.name}: missing")
            continue
        raw = f.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        n = sum(1 for line in raw.splitlines() if line.strip())
        if meta.get("sha256") and sha != meta["sha256"]:
            problems.append(f"{f.name}: sha256 {sha[:12]} != manifest {meta['sha256'][:12]}")
        if meta.get("n") is not None and n != meta["n"]:
            problems.append(f"{f.name}: {n} rows != manifest {meta['n']}")
    sample_ids = None
    nom = results / "nominatim.pred.jsonl"
    if nom.exists():
        sample_ids = set(read_predictions(nom))
    for pred in sorted(results.glob("*.pred.jsonl")):
        system = pred.name.removesuffix(".pred.jsonl")
        # a sampled run (Nominatim, rate limited) is scored on its own ids only
        own = set(read_predictions(pred)) if system in SAMPLED else None
        for suffix, only in ((".score.json", own), (".sample.score.json", sample_ids)):
            committed = results / f"{system}{suffix}"
            if not committed.exists() or (suffix != ".score.json" and only is None):
                continue
            fresh = score(pred, data, None, only)
            old = json.loads(committed.read_text(encoding="utf-8"))
            problems += [f"{committed.name}{d}" for d in _diff(fresh, old)][:20]
    if report is not None and report.exists():
        if render(results, data) != report.read_text(encoding="utf-8"):
            problems.append(f"{report.name}: differs from `tahdeed bench report` output")
    return problems


def main() -> int:
    problems = check(report=ROOT / "docs" / "BENCH_REPORT.md")
    for p in problems:
        print("DRIFT", p)
    print("bench drift check:", "FAIL" if problems else "OK (data, scores and report reproduce)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
