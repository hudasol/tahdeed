import numpy as np

from tahdeed.calibrate import empirical_radii
from tahdeed.evaluate import ece, reliability
from tahdeed.noise import make_address_queries, split_of
from tahdeed.standardize import valid_makani


def test_ece_perfect_and_overconfident():
    y = np.array([1.0] * 50 + [0.0] * 50)
    assert ece(np.full(100, 0.5), y) < 1e-9
    assert ece(np.full(100, 0.99), y) > 0.4
    assert len(reliability(np.full(100, 0.5), y)) == 1


def test_empirical_radii_needs_support_and_floors():
    out = empirical_radii({"a": list(np.linspace(0, 100, 200)), "b": [1.0] * 5, "c": [0.0] * 50})
    assert abs(out["a"] - 90.0) < 2 and "b" not in out and out["c"] >= 25.0


def test_split_is_deterministic_and_roughly_50_20_30():
    ks = [f"district-{i}" for i in range(2000)]
    assert [split_of(k) for k in ks] == [split_of(k) for k in ks]
    fr = {s: np.mean([split_of(k) == s for k in ks]) for s in ("train", "calib", "dev", "sealed")}
    assert (
        0.45 < fr["train"] < 0.55
        and 0.15 < fr["calib"] < 0.25
        and 0.15 < fr["dev"] < 0.25
        and 0.05 < fr["sealed"] < 0.15
    )


def test_noise_queries_cover_truth_and_are_reproducible(gaz):
    a = make_address_queries(gaz, 50, "train", seed=1)
    b = make_address_queries(gaz, 50, "train", seed=1)
    assert [q.text for q in a] == [q.text for q in b]
    assert all(split_of(f"{gaz.addr[q.truth_idx][8]}|"
                        f"{gaz.addr[q.truth_idx][5] or gaz.addr[q.truth_idx][4] or ''}") == "train"
               for q in a)  # fmt: skip


def test_makani_shape():
    assert valid_makani("1234567890") and not valid_makani("12345")
