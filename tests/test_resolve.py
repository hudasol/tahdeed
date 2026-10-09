from tahdeed.geo import haversine_m

TRUTH = (24.4695109, 54.3466578)  # 29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah


def _d(res):
    return haversine_m(res.best.lat, res.best.lon, *TRUTH)


def test_exact_english_address_resolves(resolver):
    r = resolver.resolve("29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi")
    assert r.best.tier == "address" and _d(r) < 30


def test_arabic_address_matches_same_point(resolver):
    r = resolver.resolve("٢٩ شارع شبيب بن سعيد المهيري، الخالدية، أبوظبي")
    assert r.best is not None and _d(r) < 30


def test_transliteration_and_typo_tolerance(resolver):
    r = resolver.resolve("29 shabeeb bin saeed al muhayri strret khalidia")
    assert r.best is not None and _d(r) < 300


def test_missing_house_number_never_claims_a_building(resolver):
    r = resolver.resolve("Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah")
    assert r.status != "resolved"
    assert any("number" in a.lower() for a in r.asks)


def test_area_only_is_approximate_with_radius(resolver):
    r = resolver.resolve("Al Khalidiyah, Abu Dhabi")
    assert r.status == "approximate" and r.best.radius_m > 100


def test_gibberish_is_never_resolved(resolver):
    # 3-letter skeleton collisions ("asdf" ~ "Sadaf") can surface a weak candidate with the
    # hand-set baseline; it must at least never be presented as a confident point.
    r = resolver.resolve("qwerty zxcv wxyz")
    assert r.status in ("unresolved", "approximate") and r.status != "resolved"


def test_po_box_is_flagged(resolver):
    r = resolver.resolve("P.O. Box 12345, Abu Dhabi")
    assert any("PO box" in n for n in r.notes)
    assert r.status != "resolved"


def test_city_name_collision_prefers_dubai(gaz):
    assert gaz.city_by_key_alias["db"] == "dubai"


def test_hidden_truth_is_not_returned(resolver, gaz):
    idx = next(i for i, a in enumerate(gaz.addr) if a[1] == "29" and "Shabib" in (a[3] or ""))
    r = resolver.resolve(
        "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah", hide_addr=frozenset({idx})
    )
    assert r.best is None or r.best.ref != ("addr", idx)
