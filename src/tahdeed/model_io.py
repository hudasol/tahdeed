"""Pickle-free model artefact and NumPy-only inference.

Training uses scikit-learn. At serving time the four calibrated heads are loaded from a ``.npz``
(plain arrays, ``allow_pickle=False``) plus a JSON manifest embedded in the same file. No code is
executed on load, scikit-learn is not required, and the manifest ties the model to the feature list
and to the gazetteer it was trained on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .calibrate import FEATURES, Policy, featurize
from .resolve import FINE_TIERS, Candidate

FORMAT_VERSION = 2


class ModelMismatch(RuntimeError):
    """The model does not belong to this code or this gazetteer."""


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class Forest:
    """All trees of one boosted classifier, flattened for simultaneous traversal."""

    feature: np.ndarray  # int32, leaves point at feature 0 with +inf threshold
    threshold: np.ndarray  # float64
    left: np.ndarray  # int32, absolute node ids (leaves point to themselves)
    right: np.ndarray
    value: np.ndarray  # float64 (leaf contribution to the raw score, 0 for inner nodes)
    roots: np.ndarray  # int32, one per tree
    baseline: float
    depth: int

    @staticmethod
    def from_sklearn(model) -> Forest:
        feats, thr, lefts, rights, vals, roots = [], [], [], [], [], []
        off, depth = 0, 0
        for plist in model._predictors:
            nodes = plist[0].nodes
            n = len(nodes)
            roots.append(off)
            for i in range(n):
                nd = nodes[i]
                if nd["is_leaf"]:
                    feats.append(0)
                    thr.append(np.inf)
                    lefts.append(off + i)
                    rights.append(off + i)
                    vals.append(float(nd["value"]))
                else:
                    feats.append(int(nd["feature_idx"]))
                    thr.append(float(nd["num_threshold"]))
                    lefts.append(off + int(nd["left"]))
                    rights.append(off + int(nd["right"]))
                    vals.append(0.0)
            depth = max(depth, int(nodes["depth"].max()) + 1)
            off += n
        return Forest(
            np.array(feats, np.int32), np.array(thr, np.float64), np.array(lefts, np.int32),
            np.array(rights, np.int32), np.array(vals, np.float64), np.array(roots, np.int32),
            float(np.ravel(model._baseline_prediction)[0]), depth,
        )  # fmt: skip

    def raw(self, X: np.ndarray) -> np.ndarray:
        n = X.shape[0]
        idx = np.tile(self.roots, (n, 1))
        rows = np.arange(n)[:, None]
        for _ in range(self.depth):
            go_left = X[rows, self.feature[idx]] <= self.threshold[idx]
            idx = np.where(go_left, self.left[idx], self.right[idx])
        return self.baseline + self.value[idx].sum(axis=1)

    def proba(self, X: np.ndarray) -> np.ndarray:
        return _sigmoid(self.raw(X))


@dataclass
class Isotonic:
    x: np.ndarray
    y: np.ndarray

    def __call__(self, p: np.ndarray) -> np.ndarray:
        return np.interp(p, self.x, self.y)


@dataclass
class NumpyRanker:
    """Drop-in replacement for :class:`tahdeed.calibrate.GBMRanker` at inference time."""

    heads: dict[str, tuple[Forest, Isotonic]]
    policy: Policy = field(default_factory=Policy)
    radii: dict[str, float] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    name: str = "gbm+isotonic (numpy)"

    def score(self, cands: list[Candidate]) -> None:
        if not cands:
            return
        X = np.array([featurize(c) for c in cands], dtype=np.float64)
        out = {h: iso(f.proba(X)) for h, (f, iso) in self.heads.items()}
        for i, c in enumerate(cands):
            c.p50 = float(out["p50"][i]) if c.tier in FINE_TIERS else 0.0
            # separately calibrated heads need not be ordered; a larger radius cannot be less likely
            c.p200 = max(float(out["p200"][i]), c.p50)
            c.p1k = max(float(out["p1k"][i]), c.p200)
            c.p_valid = float(out["valid"][i])


# ----------------------------------------------------------------------------- save / load


def _digest(arrays: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    for k in sorted(arrays):
        h.update(k.encode())
        h.update(np.ascontiguousarray(arrays[k]).tobytes())
    return h.hexdigest()


def export(ranker, path: str | Path, gazetteer_sha256: str = "", extra: dict | None = None) -> dict:
    """Write a trained scikit-learn :class:`GBMRanker` as a pickle-free artefact."""
    arrays: dict[str, np.ndarray] = {}
    for name, (model, iso) in ranker.heads.items():
        f = Forest.from_sklearn(model)
        for fld in ("feature", "threshold", "left", "right", "value", "roots"):
            arrays[f"{name}.{fld}"] = getattr(f, fld)
        arrays[f"{name}.meta"] = np.array([f.baseline, f.depth], dtype=np.float64)
        arrays[f"{name}.iso_x"] = np.asarray(iso.X_thresholds_, dtype=np.float64)
        arrays[f"{name}.iso_y"] = np.asarray(iso.y_thresholds_, dtype=np.float64)
    manifest = {
        "format": FORMAT_VERSION,
        "features": FEATURES,
        "heads": sorted(ranker.heads),
        "policy": {
            "tau": ranker.policy.tau,
            "ambiguity_margin": ranker.policy.ambiguity_margin,
            "min_separation_m": ranker.policy.min_separation_m,
        },
        "radii": ranker.radii,
        "gazetteer_sha256": gazetteer_sha256,
        "arrays_sha256": _digest(arrays),
        **(extra or {}),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"manifest": np.array(json.dumps(manifest)), **arrays}
    np.savez_compressed(path, **payload)
    return manifest


def load(path: str | Path, gazetteer_sha256: str | None = None) -> NumpyRanker:
    with np.load(path, allow_pickle=False) as z:
        manifest = json.loads(str(z["manifest"]))
        arrays = {k: z[k] for k in z.files if k != "manifest"}
    if manifest.get("format") != FORMAT_VERSION:
        raise ModelMismatch(f"model format {manifest.get('format')} != {FORMAT_VERSION}")
    if manifest["features"] != FEATURES:
        raise ModelMismatch("model was trained with a different feature list")
    if _digest(arrays) != manifest["arrays_sha256"]:
        raise ModelMismatch("model arrays failed their checksum (file corrupted or modified)")
    if gazetteer_sha256 and manifest.get("gazetteer_sha256") not in ("", gazetteer_sha256):
        raise ModelMismatch("model was trained on a different gazetteer build")
    heads = {}
    for name in manifest["heads"]:
        base, depth = arrays[f"{name}.meta"]
        f = Forest(
            arrays[f"{name}.feature"], arrays[f"{name}.threshold"], arrays[f"{name}.left"],
            arrays[f"{name}.right"], arrays[f"{name}.value"], arrays[f"{name}.roots"],
            float(base), int(depth),
        )  # fmt: skip
        heads[name] = (f, Isotonic(arrays[f"{name}.iso_x"], arrays[f"{name}.iso_y"]))
    return NumpyRanker(
        heads=heads, policy=Policy(**manifest["policy"]), radii=manifest["radii"], manifest=manifest
    )
