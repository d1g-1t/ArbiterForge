from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from arbiterforge.domain.value_objects import Institution, Regime, TribunalComposition

ICAC_SOLE_THRESHOLD_RUB = Decimal("5000000")


@dataclass(frozen=True, slots=True)
class Member:
    arbitrator_id: str
    name: str
    law_degree: bool = False
    is_chair: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Member:
        return cls(
            arbitrator_id=str(data.get("arbitrator_id") or data.get("id") or ""),
            name=str(data.get("name") or data.get("arbitrator_name") or ""),
            law_degree=bool(data.get("law_degree", False)),
            is_chair=bool(data.get("is_chair", False)),
        )


@dataclass(frozen=True, slots=True)
class TribunalCheck:
    problems: tuple[str, ...]
    advisories: tuple[str, ...]
    basis: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "problems": list(self.problems),
            "advisories": list(self.advisories),
            "basis": list(self.basis),
        }


def check_tribunal(
    composition: TribunalComposition,
    members: list[Member],
    *,
    institution: Institution,
    regime: Regime,
    claim_amount: Decimal | None = None,
    claim_currency: str = "RUB",
    chair_requirement_waived: bool = False,
) -> TribunalCheck:
    problems: list[str] = []
    advisories: list[str] = []
    basis: list[str] = []
    count = len(members)
    expected = {TribunalComposition.SOLE: 1, TribunalComposition.THREE: 3}.get(composition)
    if count == 0:
        problems.append("no_members")
    if expected is not None and count != expected:
        problems.append("member_count_mismatch")
    if count and count % 2 == 0 and institution is not Institution.MAC:
        problems.append("even_number_of_arbitrators")
        basis.append("DOM_10" if regime is Regime.DOMESTIC else "ICA_10")
    elif count and count % 2 == 0:
        basis.append("MAC_6")
    if count > 1 and sum(m.is_chair for m in members) != 1:
        problems.append("exactly_one_chair_required")
    if regime is Regime.DOMESTIC and members:
        decisive = members[0] if count == 1 else next((m for m in members if m.is_chair), None)
        if decisive is not None and not decisive.law_degree:
            any_lawyer = any(m.law_degree for m in members)
            if not (chair_requirement_waived and count > 1 and any_lawyer):
                problems.append("decisive_arbitrator_needs_law_degree")
                basis.append("DOM_11_6")
    if (
        institution is Institution.ICAC_MKAS
        and regime is Regime.DOMESTIC
        and claim_amount is not None
        and claim_currency == "RUB"
        and claim_amount <= ICAC_SOLE_THRESHOLD_RUB
        and composition is not TribunalComposition.SOLE
    ):
        advisories.append("icac_domestic_sole_arbitrator_default")
        basis.append("TPP_2024_10_23")
    return TribunalCheck(tuple(problems), tuple(advisories), tuple(dict.fromkeys(basis)))
