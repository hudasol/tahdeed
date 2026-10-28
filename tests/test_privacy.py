"""Contact details are removed before matching, including Arabic digits and spaced formats."""

import pytest

from tahdeed.privacy import redact_pii


@pytest.mark.parametrize(
    "text",
    [
        "call ٠٥٠ ١٢٣ ٤٥٦٧ near Al Wasl Rd",
        "+971 (0) 50 123 4567 Jumeirah",
        "050.123.4567 Jumeirah",
        "phone ۰۵۰۱۲۳۴۵۶۷ Jumeirah",
    ],
)
def test_phone_variants_are_removed(text):
    out, kinds = redact_pii(text)
    assert kinds == ["phone"]
    assert not any(ch.isdigit() for ch in out)


def test_makani_and_unit_numbers_survive():
    for text in ("Makani 1234567890 Marina", "Villa 12, Street 5"):
        assert redact_pii(text)[1] == []
