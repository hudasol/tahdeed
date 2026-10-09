"""Interface for an authoritative address registry (Makani, Onwani, National Address).

tahdeed ships with an OpenStreetMap gazetteer because that is what is public. A deployment with
access to an official registry would implement ``RegistryAdapter``; a confirmed hit should
override the statistical confidence, which is the case the hole-sensitivity study says matters
most. This is an interface only: it is NOT wired into ``Resolver`` yet and no official adapter
is bundled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RegistryHit:
    lat: float
    lon: float
    official_id: str  # e.g. a Makani number
    standard_form_en: str
    standard_form_ar: str


@runtime_checkable
class RegistryAdapter(Protocol):
    def lookup_id(self, official_id: str) -> RegistryHit | None:
        """Exact lookup by official identifier (Makani number, Onwani id)."""

    def confirm(self, lat: float, lon: float, radius_m: float) -> RegistryHit | None:
        """Nearest official record within ``radius_m`` of a point, if any."""
