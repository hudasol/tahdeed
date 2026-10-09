from tahdeed.parse import parse


def test_makani_extracted_and_removed():
    pq = parse("Makani 12345 67890, Business Bay")
    assert pq.makani == "1234567890"
    assert "12345" not in pq.tokens


def test_makani_arabic_digits():
    pq = parse("مكاني ١٢٣٤٥ ٦٧٨٩٠")
    assert pq.makani == "1234567890"


def test_po_box_is_flagged_not_a_location():
    pq = parse("P.O. Box 12345, Dubai")
    assert pq.po_box == "12345"
    assert "po_box" in pq.notes
    assert pq.makani is None


def test_building_number_with_keyword():
    pq = parse("Villa 14, Al Safa 1, Dubai")
    nums = {n.value: n for n in pq.numbers}
    assert nums["14"].keyword == "villa"
    assert nums["1"].keyword is None


def test_leading_number():
    pq = parse("29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah, Abu Dhabi")
    first = pq.numbers[0]
    assert first.value == "29" and first.leading and not first.adjacent_type


def test_street_number_is_adjacent_to_type():
    pq = parse("Street 23, Al Quoz")
    n = pq.numbers[0]
    assert n.value == "23" and n.adjacent_type


def test_unit_removed_from_name_tokens():
    pq = parse("Apt 301, Building 7, Al Wasl Road")
    assert pq.unit == "apt 301"
    body = [pq.tokens[i] for i in pq.body_indices()]
    assert "301" not in body and "apt" not in body


def test_landmark_relation_english():
    pq = parse("Villa 14, near Spinneys Umm Suqeim, Dubai")
    assert pq.relation == "near"
    assert pq.landmark_tokens == ["spinneys", "umm", "suqeim"]
    assert "spinneys" not in [pq.tokens[i] for i in pq.body_indices()]


def test_landmark_relation_arabic():
    pq = parse("شارع الأسد بجانب المطعم")
    assert pq.relation == "next_to"
    assert pq.landmark_tokens == ["مطعم"] or pq.landmark_tokens == ["المطعم"]


def test_multiword_relation():
    pq = parse("in front of Dubai Mall")
    assert pq.relation == "in_front"
    assert pq.landmark_tokens == ["dubai", "mall"]


def test_plain_address_has_no_relation():
    pq = parse("Al Khalidiyah, Abu Dhabi")
    assert pq.relation is None and pq.landmark_span is None


def test_postcode_keyword():
    pq = parse("Postcode 20039 Abu Dhabi")
    assert pq.postcode_hint == "20039"
