from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbiterforge.domain.value_objects import Institution, Regime


class DisputeCategory(StrEnum):
    COMMERCIAL = "commercial"
    BANKRUPTCY = "bankruptcy"
    STATE_REGISTRATION_REFUSAL = "state_registration_refusal"
    IP_COLLECTIVE_MANAGEMENT = "ip_collective_management"
    ADMINISTRATIVE = "administrative"
    PRIVATIZATION = "privatization"
    PUBLIC_PROCUREMENT_44FZ = "public_procurement_44fz"
    ENVIRONMENTAL_DAMAGE = "environmental_damage"
    CORPORATE_MEETING_OR_STATE_ACTS = "corporate_meeting_or_state_acts"
    CORPORATE_STRATEGIC_COMPANY = "corporate_strategic_company"
    CORPORATE_JSC_TAKEOVER = "corporate_jsc_takeover"
    CORPORATE_EXCLUSION = "corporate_exclusion"
    CORPORATE_SHARES_OWNERSHIP = "corporate_shares_ownership"
    SHAREHOLDER_AGREEMENT = "shareholder_agreement"
    CORPORATE_INTERNAL = "corporate_internal"
    PROCUREMENT_223FZ = "procurement_223fz"


class Arbitrability(StrEnum):
    ARBITRABLE = "ARBITRABLE"
    NOT_ARBITRABLE = "NOT_ARBITRABLE"
    ONLY_PDAU = "ONLY_PDAU"
    REQUIRES_ALL_PARTICIPANTS = "REQUIRES_ALL_PARTICIPANTS"


_RULES: dict[DisputeCategory, tuple[Arbitrability, tuple[str, ...]]] = {
    DisputeCategory.COMMERCIAL: (Arbitrability.ARBITRABLE, ("APK_33_1",)),
    DisputeCategory.BANKRUPTCY: (Arbitrability.NOT_ARBITRABLE, ("APK_33_2", "APK_27_6")),
    DisputeCategory.STATE_REGISTRATION_REFUSAL: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_27_6"),
    ),
    DisputeCategory.IP_COLLECTIVE_MANAGEMENT: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_27_6"),
    ),
    DisputeCategory.ADMINISTRATIVE: (Arbitrability.NOT_ARBITRABLE, ("APK_33_2",)),
    DisputeCategory.PRIVATIZATION: (Arbitrability.NOT_ARBITRABLE, ("APK_33_2",)),
    DisputeCategory.PUBLIC_PROCUREMENT_44FZ: (Arbitrability.NOT_ARBITRABLE, ("APK_33_2",)),
    DisputeCategory.ENVIRONMENTAL_DAMAGE: (Arbitrability.NOT_ARBITRABLE, ("APK_33_2",)),
    DisputeCategory.CORPORATE_MEETING_OR_STATE_ACTS: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_225_1_2"),
    ),
    DisputeCategory.CORPORATE_STRATEGIC_COMPANY: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_225_1_2"),
    ),
    DisputeCategory.CORPORATE_JSC_TAKEOVER: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_225_1_2"),
    ),
    DisputeCategory.CORPORATE_EXCLUSION: (
        Arbitrability.NOT_ARBITRABLE,
        ("APK_33_2", "APK_225_1_2"),
    ),
    DisputeCategory.CORPORATE_SHARES_OWNERSHIP: (
        Arbitrability.ONLY_PDAU,
        ("DOM_45_7", "DOM_45_7_1"),
    ),
    DisputeCategory.SHAREHOLDER_AGREEMENT: (Arbitrability.ONLY_PDAU, ("DOM_45_7", "DOM_45_7_1")),
    DisputeCategory.CORPORATE_INTERNAL: (
        Arbitrability.REQUIRES_ALL_PARTICIPANTS,
        ("APK_225_1_3", "DOM_45_7"),
    ),
    DisputeCategory.PROCUREMENT_223FZ: (Arbitrability.ONLY_PDAU, ("DOM_45_10",)),
}


@dataclass(frozen=True, slots=True)
class ArbitrabilityDecision:
    category: DisputeCategory
    outcome: Arbitrability
    admissible: bool
    problems: tuple[str, ...]
    warnings: tuple[str, ...]
    basis: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "outcome": self.outcome.value,
            "admissible": self.admissible,
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "basis": list(self.basis),
        }


def assess_arbitrability(
    category: DisputeCategory,
    institution: Institution,
    *,
    seat_country: str = "RU",
    regime: Regime | None = None,
    all_participants_signed: bool = False,
    sanctions_involved: bool = False,
) -> ArbitrabilityDecision:
    outcome, basis = _RULES[category]
    problems: list[str] = []
    warnings: list[str] = []
    if outcome is Arbitrability.NOT_ARBITRABLE:
        problems.append("dispute_not_arbitrable")
    elif outcome is Arbitrability.ONLY_PDAU:
        if not institution.is_institutional:
            problems.append("ad_hoc_not_allowed_for_category")
        if category is DisputeCategory.PROCUREMENT_223FZ and seat_country.upper() != "RU":
            warnings.append("seat_abroad_outside_45_10_scope")
    elif outcome is Arbitrability.REQUIRES_ALL_PARTICIPANTS:
        if not institution.is_institutional:
            problems.append("ad_hoc_not_allowed_for_category")
        if seat_country.upper() != "RU":
            problems.append("seat_must_be_in_russia")
        if not all_participants_signed:
            problems.append("all_participants_must_sign_agreement")
        warnings.append("institution_must_have_deposited_corporate_rules")
    if institution is Institution.RAC and outcome in {
        Arbitrability.ONLY_PDAU,
        Arbitrability.REQUIRES_ALL_PARTICIPANTS,
    }:
        warnings.append("check_pdau_status_in_minjust_list")
    if sanctions_involved and (regime is Regime.FOREIGN_SEAT or seat_country.upper() != "RU"):
        warnings.append("sanctions_exclusive_jurisdiction_risk")
        basis = (*basis, "APK_248_1")
    return ArbitrabilityDecision(
        category=category,
        outcome=outcome,
        admissible=not problems,
        problems=tuple(problems),
        warnings=tuple(warnings),
        basis=basis,
    )
