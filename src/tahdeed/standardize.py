"""Onwani-style standard form (building, street, district, city) in English and Arabic.

This is a *format*, not an official identifier: tahdeed never invents Makani / Onwani / National
Address codes. A recognised Makani is only checked for shape (10 digits).
"""

from __future__ import annotations

from .resolve import Candidate, Resolution


def _join(*parts: str | None) -> str:
    return ", ".join(p for p in parts if p)


def standard_form(c: Candidate) -> dict[str, str]:
    """Bilingual single-line form for a candidate, as complete as its tier allows."""
    L = c.label
    if c.tier in ("address", "interpolated"):
        b = L.get("building") or ""
        en = _join(
            " ".join(x for x in (b, L.get("street_en")) if x) or None,
            L.get("district_en"), L.get("city_en"),
        )  # fmt: skip
        ar = _join(
            " ".join(x for x in (b, L.get("street_ar")) if x) or None,
            L.get("district_ar"), L.get("city_ar"),
        )  # fmt: skip
        return {"en": en, "ar": ar, "postcode": L.get("postcode") or ""}
    if c.tier == "poi":
        return {
            "en": _join(L.get("name_en"), L.get("street"), L.get("city_en")),
            "ar": _join(L.get("name_ar"), L.get("city_ar")),
            "postcode": "",
        }
    if c.tier in ("street", "street_area"):
        return {
            "en": _join(
                L.get("street_en") or L.get("name"), L.get("district_en"), L.get("city_en")
            ),
            "ar": _join(L.get("street_ar"), L.get("district_ar"), L.get("city_ar")),
            "postcode": "",
        }
    if c.tier == "area":
        return {
            "en": _join(L.get("area_en"), L.get("city_en")),
            "ar": _join(L.get("area_ar"), L.get("city_ar")),
            "postcode": "",
        }
    if c.tier == "landmark":
        return {"en": _join(L.get("name_en"), L.get("city_en")),
                "ar": _join(L.get("name_ar"), L.get("city_ar")), "postcode": ""}  # fmt: skip
    return {"en": _join(L.get("city_en")), "ar": _join(L.get("city_ar")), "postcode": ""}


def valid_makani(s: str | None) -> bool:
    return bool(s) and len(s) == 10 and s.isdigit()


def candidate_json(c: Candidate) -> dict:
    return {
        "tier": c.tier,
        "lat": round(c.lat, 6),
        "lon": round(c.lon, 6),
        "radius_m": round(c.radius_m),
        "p_within_50m": None if c.p50 is None else round(c.p50, 3),
        "p_correct_at_tier": None if c.p_valid is None else round(c.p_valid, 3),
        "standard": standard_form(c),
        "evidence": {k: v for k, v in c.evidence.items() if k not in ("keys", "area_keys")},
    }


def resolution_json(r: Resolution) -> dict:
    return {
        "query": r.query,
        "status": r.status,
        "best": candidate_json(r.best) if r.best else None,
        "alternatives": [candidate_json(c) for c in r.alternatives],
        "asks": r.asks,
        "notes": r.notes,
        "makani": {"value": r.parsed.makani, "well_formed": valid_makani(r.parsed.makani)}
        if r.parsed.makani else None,
    }  # fmt: skip
