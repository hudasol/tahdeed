"""Build a tiny gazetteer + trained model from the committed test fixture, for the Docker smoke test.

    python scripts/make_smoke_model.py OUT_DIR [--n-train 1500]

Writes ``OUT_DIR/gazetteer.sqlite`` (a byte copy of ``tests/fixtures/mini.sqlite``, ~2.5 MB of
OpenStreetMap data around Al Khalidiyah, Abu Dhabi; (c) OpenStreetMap contributors, ODbL) and
``OUT_DIR/ranker.npz`` (a small model trained on it with the real training code). The model manifest
records the gazetteer's sha256, so the service loads it in strict mode (``TAHDEED_STRICT=1``) exactly
as it would load a real model. The model is only good enough to exercise the service, not to
evaluate anything. Mount ``OUT_DIR`` at ``/data`` in the container.

Needs ``pip install -e ".[train]"`` (scikit-learn). Takes well under a minute.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mini.sqlite"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--n-train", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))  # works with or without `pip install -e .`
    from tahdeed.gazetteer import Gazetteer
    from tahdeed.model_io import export
    from tahdeed.service import load_resolver
    from tahdeed.train import train

    a.out_dir.mkdir(parents=True, exist_ok=True)
    db = a.out_dir / "gazetteer.sqlite"
    model = a.out_dir / "ranker.npz"
    shutil.copyfile(FIXTURE, db)

    g = Gazetteer.load(db)
    ranker, _ = train(
        g, n_train=a.n_train, n_calib=max(300, a.n_train // 3), workers=a.workers, verbose=False
    )
    export(ranker, model, g.sha256, {"n_train": a.n_train, "purpose": "docker smoke test only"})

    # Prove what the container will do: strict load (raises on any mismatch) and resolve once.
    r = load_resolver(db, model, strict=True)
    assert r.degraded_reason is None, r.degraded_reason
    res = r.resolve("29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah")
    assert res.best is not None, "smoke model cannot resolve the fixture address"
    print(
        f"smoke data ready in {a.out_dir}: gazetteer {g.sha256[:12]}, model {model.stat().st_size} B"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
