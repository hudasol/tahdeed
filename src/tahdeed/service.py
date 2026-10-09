"""Shared loader: gazetteer + trained ranker -> Resolver."""

from __future__ import annotations

import os
from pathlib import Path

from .calibrate import GBMRanker, HeuristicRanker
from .gazetteer import Gazetteer
from .resolve import Resolver

DEFAULT_DB = Path(os.environ.get("TAHDEED_DB", "data/gazetteer.sqlite"))
DEFAULT_MODEL = Path(os.environ.get("TAHDEED_MODEL", "data/models/ranker.pkl"))


def load_resolver(db: Path = DEFAULT_DB, model: Path = DEFAULT_MODEL) -> Resolver:
    g = Gazetteer.load(db)
    if Path(model).exists():
        r = GBMRanker.load(model)
        return Resolver(g, ranker=r, radii=r.radii)
    return Resolver(g, ranker=HeuristicRanker())
