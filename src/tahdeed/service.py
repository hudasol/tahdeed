"""Shared loader: gazetteer + trained ranker -> Resolver (pickle-free, provenance-checked)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .calibrate import HeuristicRanker
from .gazetteer import Gazetteer
from .model_io import ModelMismatch
from .model_io import load as load_model
from .resolve import Resolver

log = logging.getLogger("tahdeed")

DEFAULT_DB = Path(os.environ.get("TAHDEED_DB", "data/gazetteer.sqlite"))
DEFAULT_MODEL = Path(os.environ.get("TAHDEED_MODEL", "data/models/ranker.npz"))


def load_resolver(
    db: Path = DEFAULT_DB, model: Path = DEFAULT_MODEL, strict: bool | None = None
) -> Resolver:
    """Load gazetteer and model.

    With ``strict`` (default: env ``TAHDEED_STRICT=1``) a missing or mismatched model raises.
    Otherwise it degrades to the uncalibrated heuristic and the resolver says so
    (``resolver.degraded_reason``), so callers never mistake those scores for probabilities.
    """
    if strict is None:
        strict = os.environ.get("TAHDEED_STRICT", "0") == "1"
    g = Gazetteer.load(db)
    reason = None
    try:
        if not Path(model).exists():
            raise ModelMismatch(f"model file not found: {model}")
        r = load_model(model, gazetteer_sha256=g.sha256)
        res = Resolver(g, ranker=r, radii=r.radii)
    except (ModelMismatch, OSError, ValueError, KeyError) as ex:
        if strict:
            raise
        reason = str(ex)
        log.warning("degraded mode: %s", reason)
        res = Resolver(g, ranker=HeuristicRanker())
    res.degraded_reason = reason
    return res
