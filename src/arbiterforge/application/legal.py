from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from arbiterforge.domain.arbitrability import DisputeCategory, assess_arbitrability
from arbiterforge.domain.calendar import DEFAULT_CALENDAR, TRANSFER_ACTS
from arbiterforge.domain.legal_basis import NORMS, norms
from arbiterforge.domain.regime import RegimeInput, determine_regime
from arbiterforge.domain.terms import ComputationRule, TermSpec, TermUnit, compute_deadline
from arbiterforge.domain.tribunal import Member, check_tribunal
from arbiterforge.domain.value_objects import Institution, Regime, TribunalComposition

RULE_BASIS = {
    ComputationRule.APK: ("APK_113", "APK_114"),
    ComputationRule.CIVIL: ("GK_191", "GK_192", "GK_193"),
}


def _with_norms(data: dict[str, Any]) -> dict[str, Any]:
    return {**data, "norms": norms(*data.get("basis", ()))}


def compute_term(start: date, amount: int, unit: TermUnit, rule: ComputationRule) -> dict[str, Any]:
    due = compute_deadline(start, TermSpec(amount, unit, rule))
    basis = (*RULE_BASIS[rule], "TK_112")
    return _with_norms(
        {
            "start": start.isoformat(),
            "amount": amount,
            "unit": unit.value,
            "rule": rule.value,
            "due_date": due.isoformat(),
            "due_is_working_day": DEFAULT_CALENDAR.is_working_day(due),
            "basis": list(basis),
            "calendar_acts": [TRANSFER_ACTS[y] for y in sorted({start.year, due.year})],
        }
    )


def regime(data: RegimeInput) -> dict[str, Any]:
    return _with_norms(determine_regime(data).to_dict())


def arbitrability(
    category: DisputeCategory,
    institution: Institution,
    *,
    seat_country: str,
    all_participants_signed: bool,
    sanctions_involved: bool,
) -> dict[str, Any]:
    decision = assess_arbitrability(
        category,
        institution,
        seat_country=seat_country,
        all_participants_signed=all_participants_signed,
        sanctions_involved=sanctions_involved,
    )
    return _with_norms(decision.to_dict())


def tribunal(
    composition: TribunalComposition,
    members: list[dict[str, Any]],
    *,
    institution: Institution,
    regime_value: Regime,
    claim_amount: Decimal | None,
    claim_currency: str,
    chair_requirement_waived: bool,
) -> dict[str, Any]:
    check = check_tribunal(
        composition,
        [Member.from_dict(m) for m in members],
        institution=institution,
        regime=regime_value,
        claim_amount=claim_amount,
        claim_currency=claim_currency,
        chair_requirement_waived=chair_requirement_waived,
    )
    return _with_norms(check.to_dict())


def working_days(year: int) -> dict[str, Any]:
    off = DEFAULT_CALENDAR.non_working_days(year)
    return {
        "year": year,
        "non_working_days": [d.isoformat() for d in off],
        "non_working_weekdays": [d.isoformat() for d in off if d.weekday() < 5],
        "act": TRANSFER_ACTS[year],
        "basis": ["TK_112"],
    }


def all_norms() -> list[dict[str, Any]]:
    return [n.to_dict() for n in NORMS.values()]
