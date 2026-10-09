import time

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tahdeed.model_io import ModelMismatch, export, load
from tahdeed.normalize import normalize_text, skeleton
from tahdeed.parse import parse

TEXT = st.text(max_size=300)
ARABIC_ISH = st.text(
    alphabet=st.characters(min_codepoint=0x0600, max_codepoint=0x06FF), max_size=120
)


@settings(max_examples=300, deadline=None)
@given(TEXT)
def test_normalize_and_parse_never_raise(t):
    normalize_text(t)
    skeleton(t)
    parse(t)


@settings(
    max_examples=120, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.one_of(TEXT, ARABIC_ISH, st.text(alphabet="0123456789 -/.,٠١٢٣٤٥٦٧٨٩", max_size=200)))
def test_resolve_never_raises_and_is_fast(resolver, t):
    t0 = time.perf_counter()
    r = resolver.resolve(t)
    assert r.status in {"resolved", "approximate", "ambiguous", "unresolved"}
    assert (time.perf_counter() - t0) < 2.0
    if r.best is not None:
        assert -90 <= r.best.lat <= 90 and -180 <= r.best.lon <= 180


def test_pathological_inputs_are_bounded(resolver):
    for t in [
        "a" * 5000,
        "1 " * 400,
        "شارع " * 300,
        "‮" * 100 + "Al Khalidiyah",
        "\x00\x01\x02",
        "9" * 4000,
    ]:
        t0 = time.perf_counter()
        r = resolver.resolve(t)
        assert r.status in {"resolved", "approximate", "ambiguous", "unresolved"}
        assert (time.perf_counter() - t0) < 2.0


def test_resolution_is_deterministic(resolver):
    q = "٢٩ شارع شبيب بن سعيد المهيري، الخالدية، أبوظبي"
    a = resolver.resolve(q)
    b = resolver.resolve(q)
    assert (a.status, a.best.lat, a.best.lon, a.best.p50) == (
        b.status,
        b.best.lat,
        b.best.lon,
        b.best.p50,
    )


def test_model_roundtrip_matches_sklearn_and_detects_tampering(tmp_path):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression

    from tahdeed.calibrate import FEATURES, GBMRanker

    rng = np.random.default_rng(0)
    X = rng.integers(-1, 20, size=(400, len(FEATURES))).astype(float)
    y = (X[:, 1] + rng.normal(size=400) > 8).astype(int)
    heads = {}
    for h in ("p50", "p200", "p1k", "valid"):
        m = HistGradientBoostingClassifier(max_iter=20, random_state=0).fit(X, y)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
            m.predict_proba(X)[:, 1], y
        )
        heads[h] = (m, iso)
    path = tmp_path / "m.npz"
    export(GBMRanker(heads=heads), path, "abc")
    n = load(path, gazetteer_sha256="abc")
    for h, (m, iso) in heads.items():
        want = iso.predict(m.predict_proba(X)[:, 1])
        got = n.heads[h][1](n.heads[h][0].proba(X))
        assert np.allclose(want, got, atol=1e-9)
    try:
        load(path, gazetteer_sha256="different")
    except ModelMismatch:
        pass
    else:
        raise AssertionError("gazetteer mismatch must be refused")
    # flip one value in the arrays: checksum must catch it
    with np.load(path, allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["p50.value"] = d["p50.value"] + 1e-3
    np.savez_compressed(tmp_path / "bad.npz", **d)
    try:
        load(tmp_path / "bad.npz")
    except ModelMismatch:
        pass
    else:
        raise AssertionError("tampered model must be refused")


def test_pii_is_removed_before_matching():
    from tahdeed.privacy import redact_pii

    t, kinds = redact_pii("Villa 5 Al Wasl Rd Dubai call 050 123 4567 or a.b@x.com +971 4 123 4567")
    assert "050" not in t and "@" not in t and "971" not in t
    assert set(kinds) == {"email", "phone"}
    t2, k2 = redact_pii("12345 67890 Makani, 29 Khalidiyah")
    assert k2 == [] and "12345" in t2
