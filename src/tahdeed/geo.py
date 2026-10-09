"""Small geodesy helpers and the static list of UAE cities/regions."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def haversine_np(lat1, lon1, lat2, lon2):
    """Vectorized haversine; arguments broadcast."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.minimum(1.0, np.sqrt(a)))


@dataclass(frozen=True)
class City:
    key: str  # canonical English id
    en: str
    ar: str
    emirate: str
    lat: float
    lon: float
    aliases: tuple[str, ...] = ()


# Approximate centres, used only to attach a region to streets/POIs that carry no
# addr:city tag, and as the coarsest fallback location. Coordinates are rounded.
CITIES: tuple[City, ...] = (
    City("abu dhabi", "Abu Dhabi", "أبوظبي", "Abu Dhabi", 24.4539, 54.3773, ("abudhabi", "auh")),
    City("al ain", "Al Ain", "العين", "Abu Dhabi", 24.2075, 55.7447),
    City("ruwais", "Al Ruwais", "الرويس", "Abu Dhabi", 24.1100, 52.7300, ("ruwais",)),
    City("madinat zayed", "Madinat Zayed", "مدينة زايد", "Abu Dhabi", 23.6580, 53.7050),
    City("liwa", "Liwa", "ليوا", "Abu Dhabi", 23.1300, 53.7900),
    City("dubai", "Dubai", "دبي", "Dubai", 25.2048, 55.2708, ("dxb",)),
    City("hatta", "Hatta", "حتا", "Dubai", 24.8000, 56.1160),
    City("sharjah", "Sharjah", "الشارقة", "Sharjah", 25.3463, 55.4209, ("shj",)),
    City("khor fakkan", "Khor Fakkan", "خورفكان", "Sharjah", 25.3395, 56.3568),
    City("kalba", "Kalba", "كلباء", "Sharjah", 25.0453, 56.3583),
    City("ajman", "Ajman", "عجمان", "Ajman", 25.4052, 55.5136),
    City(
        "umm al quwain", "Umm Al Quwain", "أم القيوين", "Umm Al Quwain", 25.5647, 55.5534, ("uaq",)
    ),  # fmt: skip
    City(
        "ras al khaimah",
        "Ras Al Khaimah",
        "رأس الخيمة",
        "Ras Al Khaimah",
        25.7895,
        55.9432,
        ("rak",),
    ),  # fmt: skip
    City("fujairah", "Fujairah", "الفجيرة", "Fujairah", 25.1288, 56.3265),
    City("dibba", "Dibba Al Fujairah", "دبا الفجيرة", "Fujairah", 25.6180, 56.2730),
)

CITY_BY_KEY = {c.key: c for c in CITIES}


def nearest_city(lat: float, lon: float) -> City:
    best, bd = CITIES[0], float("inf")
    for c in CITIES:
        d = haversine_m(lat, lon, c.lat, c.lon)
        if d < bd:
            best, bd = c, d
    return best
