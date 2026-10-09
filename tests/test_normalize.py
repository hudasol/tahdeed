import pytest

from tahdeed.normalize import (
    has_arabic,
    name_tokens,
    normalize_arabic,
    script_of,
    skeleton,
    street_type_of,
    to_ascii_digits,
    tokenize,
)


def test_digits():
    assert to_ascii_digits("شارع ٢٣ و ۱۲") == "شارع 23 و 12"


def test_arabic_unify_and_diacritics():
    assert normalize_arabic("الرُّبَيِّع") == "الربيع"
    assert normalize_arabic("أحمد") == normalize_arabic("احمد")
    assert normalize_arabic("مدينـة") == "مدينة"


def test_script_detection():
    assert script_of("Al Khalidiyah") == "en"
    assert script_of("الخالدية") == "ar"
    assert script_of("Villa 14 شارع الأسد") == "mixed"
    assert has_arabic("x ع")


def test_tokenize_keeps_slash_numbers():
    assert tokenize("Flat 12/3, Al-Wasl Rd.") == ["flat", "12/3", "al", "wasl", "rd"]


def test_name_tokens_drop_articles_and_types():
    assert name_tokens("Al Khalidiyah Street") == ["khalidiyah"]
    assert name_tokens("شارع الخالدية") == ["خالدية"]
    # the article is kept when it is the only token
    assert name_tokens("Al") == ["al"]


@pytest.mark.parametrize(
    "a,b",
    [
        ("Jumeirah", "Jumeira"),
        ("Jumeirah", "جميرا"),
        ("Jumeira", "جميرة"),
        ("Abu Dhabi", "أبوظبي"),
        ("Abu Dhabi", "AbuDhabi"),
        ("Al Khalidiyah", "الخالدية"),
        ("Khalidiya", "Al Khalidiyah"),
        ("Dubai", "دبي"),
        ("Al Ain", "العين"),
        ("Shabib Bin Saeed Al Muhairi Street", "شارع شبيب بن سعيد المهيري"),
        ("Al Qusais", "القصيص"),
        ("Muhammad", "محمد"),
        ("Zayed", "زايد"),
        ("Sheikh Zayed Road", "طريق الشيخ زايد"),
    ],
)
def test_cross_script_skeleton_equal(a, b):
    sa, sb = skeleton(a), skeleton(b)
    assert sa and sa == sb, (a, sa, b, sb)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Al Khalidiyah", "Al Khalifa"),
        ("Dubai", "Sharjah"),
        ("Al Ain", "Al Dhafra"),
    ],
)
def test_distinct_names_stay_distinct(a, b):
    assert skeleton(a) != skeleton(b)


def test_street_type():
    assert street_type_of("Hazza Bin Zayed Street") == "street"
    assert street_type_of("طريق الاتحاد") == "road"
    assert street_type_of("Al Safa") is None
