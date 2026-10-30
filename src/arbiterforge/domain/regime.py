from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arbiterforge.domain.legal_basis import DOMESTIC_LAW, ICA_LAW
from arbiterforge.domain.value_objects import Regime

HOME_COUNTRY = "RU"


@dataclass(frozen=True, slots=True)
class RegimeInput:
    seat_country: str = HOME_COUNTRY
    party_countries: tuple[str, ...] = ()
    performance_abroad: bool = False
    closest_connection_abroad: bool = False
    foreign_investment: bool = False


@dataclass(frozen=True, slots=True)
class RegimeDecision:
    regime: Regime
    applicable_law: str
    reasons: tuple[str, ...]
    basis: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "applicable_law": self.applicable_law,
            "reasons": list(self.reasons),
            "basis": list(self.basis),
        }


def determine_regime(data: RegimeInput) -> RegimeDecision:
    seat = data.seat_country.upper()
    if seat != HOME_COUNTRY:
        return RegimeDecision(
            Regime.FOREIGN_SEAT,
            ICA_LAW,
            ("seat_abroad",),
            ("ICA_1_1",),
        )
    reasons = []
    if any(c.upper() != HOME_COUNTRY for c in data.party_countries):
        reasons.append("party_abroad")
    if data.performance_abroad:
        reasons.append("performance_abroad")
    if data.closest_connection_abroad:
        reasons.append("closest_connection_abroad")
    if data.foreign_investment:
        reasons.append("foreign_investment")
    if reasons:
        return RegimeDecision(Regime.INTERNATIONAL, ICA_LAW, tuple(reasons), ("ICA_1_3",))
    return RegimeDecision(Regime.DOMESTIC, DOMESTIC_LAW, ("no_foreign_element",), ())
