"""Merge partial `tahdeed ablate-poi` outputs (models scored in parallel runs) into one file.

    python scripts/merge_poi_ablation.py docs/poi_ablation.json part1.json part2.json ...

Refuses to merge runs on different gazetteers or splits. Values are copied unchanged.
"""

import json
import sys


def main(out: str, *parts: str) -> int:
    merged: dict = {}
    for p in parts:
        d = json.load(open(p, encoding="utf-8"))
        if merged and (d["gazetteer_sha256"], d["split"]) != (
            merged["gazetteer_sha256"],
            merged["split"],
        ):
            raise SystemExit(f"{p}: different gazetteer or split")
        models = d.pop("models")
        if not merged:
            merged = {**d, "models": {}}
        merged["models"].update(models)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=1)
    print(out, list(merged["models"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
