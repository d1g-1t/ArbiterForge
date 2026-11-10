from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbiterforge.domain.arbitrability import (
    _RULES,
    Arbitrability,
    DisputeCategory,
    assess_arbitrability,
)
from arbiterforge.domain.legal_basis import NORMS, norms
from arbiterforge.domain.regime import RegimeInput, determine_regime
from arbiterforge.domain.tribunal import Member, check_tribunal
from arbiterforge.domain.value_objects import Institution, Regime, TribunalComposition

countries = st.sampled_from(["RU", "KZ", "BY", "CN", "AE", "ru"])


def test_every_rule_cites_registered_norms() -> None:
    for outcome, basis in _RULES.values():
        assert basis
        assert isinstance(outcome, Arbitrability)
        for code in basis:
            assert code in NORMS
    assert set(_RULES) == set(DisputeCategory)


def test_norm_registry_is_complete() -> None:
    for norm in NORMS.values():
        assert norm.quote
        assert norm.source.startswith("http")
        assert norm.article
    assert norms("APK_113")[0]["article"] == "ч. 3–4 ст. 113"


@given(countries, st.lists(countries, max_size=4), st.booleans(), st.booleans(), st.booleans())
def test_regime_classification(
    seat: str, parties: list[str], perf: bool, conn: bool, invest: bool
) -> None:
    decision = determine_regime(RegimeInput(seat, tuple(parties), perf, conn, invest))
    foreign = any(c.upper() != "RU" for c in parties) or perf or conn or invest
    if seat.upper() != "RU":
        assert decision.regime is Regime.FOREIGN_SEAT
        assert decision.basis == ("ICA_1_1",)
    elif foreign:
        assert decision.regime is Regime.INTERNATIONAL
        assert decision.basis == ("ICA_1_3",)
        assert decision.reasons
    else:
        assert decision.regime is Regime.DOMESTIC
    assert decision.to_dict()["regime"] == decision.regime.value


@pytest.mark.parametrize("category", list(DisputeCategory))
@pytest.mark.parametrize("institution", list(Institution))
def test_arbitrability_matrix(category: DisputeCategory, institution: Institution) -> None:
    decision = assess_arbitrability(category, institution, all_participants_signed=True)
    outcome = _RULES[category][0]
    if outcome is Arbitrability.NOT_ARBITRABLE:
        assert not decision.admissible
    elif outcome is Arbitrability.ARBITRABLE:
        assert decision.admissible
    else:
        assert decision.admissible is institution.is_institutional


def test_corporate_internal_requirements() -> None:
    decision = assess_arbitrability(
        DisputeCategory.CORPORATE_INTERNAL, Institution.ICAC_MKAS, seat_country="AE"
    )
    assert set(decision.problems) == {
        "seat_must_be_in_russia",
        "all_participants_must_sign_agreement",
    }
    assert "institution_must_have_deposited_corporate_rules" in decision.warnings
    rac = assess_arbitrability(
        DisputeCategory.SHAREHOLDER_AGREEMENT, Institution.RAC, all_participants_signed=True
    )
    assert "check_pdau_status_in_minjust_list" in rac.warnings


def test_223fz_and_sanctions_warnings() -> None:
    abroad = assess_arbitrability(
        DisputeCategory.PROCUREMENT_223FZ, Institution.ICAC_MKAS, seat_country="CN"
    )
    assert "seat_abroad_outside_45_10_scope" in abroad.warnings
    sanctions = assess_arbitrability(
        DisputeCategory.COMMERCIAL,
        Institution.AD_HOC,
        seat_country="AE",
        regime=Regime.FOREIGN_SEAT,
        sanctions_involved=True,
    )
    assert sanctions.admissible
    assert "APK_248_1" in sanctions.basis
    assert sanctions.to_dict()["warnings"] == ["sanctions_exclusive_jurisdiction_risk"]


def members(n: int, *, chair_law: bool = True, chair: bool = True) -> list[Member]:
    return [
        Member(
            f"a{i}", f"A{i}", law_degree=chair_law if i == 0 else False, is_chair=chair and i == 0
        )
        for i in range(n)
    ]


def test_tribunal_valid_three() -> None:
    check = check_tribunal(
        TribunalComposition.THREE,
        members(3),
        institution=Institution.ICAC_MKAS,
        regime=Regime.DOMESTIC,
    )
    assert check.ok
    assert check.to_dict()["ok"] is True


def test_tribunal_count_and_parity() -> None:
    even = check_tribunal(
        TribunalComposition.OTHER,
        members(2),
        institution=Institution.ICAC_MKAS,
        regime=Regime.INTERNATIONAL,
    )
    assert "even_number_of_arbitrators" in even.problems
    assert "ICA_10" in even.basis
    mac = check_tribunal(
        TribunalComposition.OTHER,
        members(2),
        institution=Institution.MAC,
        regime=Regime.INTERNATIONAL,
    )
    assert mac.ok
    assert "MAC_6" in mac.basis
    mismatch = check_tribunal(
        TribunalComposition.SOLE,
        members(3),
        institution=Institution.AD_HOC,
        regime=Regime.INTERNATIONAL,
    )
    assert "member_count_mismatch" in mismatch.problems
    empty = check_tribunal(
        TribunalComposition.SOLE, [], institution=Institution.AD_HOC, regime=Regime.DOMESTIC
    )
    assert "no_members" in empty.problems
    no_chair = check_tribunal(
        TribunalComposition.THREE,
        members(3, chair=False),
        institution=Institution.AD_HOC,
        regime=Regime.INTERNATIONAL,
    )
    assert "exactly_one_chair_required" in no_chair.problems


def test_domestic_law_degree_rule_and_waiver() -> None:
    lacking = members(3, chair_law=False)
    check = check_tribunal(
        TribunalComposition.THREE, lacking, institution=Institution.AD_HOC, regime=Regime.DOMESTIC
    )
    assert "decisive_arbitrator_needs_law_degree" in check.problems
    assert "DOM_11_6" in check.basis
    waived_with_lawyer = [*lacking[:2], Member("a2", "A2", law_degree=True)]
    waived = check_tribunal(
        TribunalComposition.THREE,
        waived_with_lawyer,
        institution=Institution.AD_HOC,
        regime=Regime.DOMESTIC,
        chair_requirement_waived=True,
    )
    assert waived.ok
    sole = check_tribunal(
        TribunalComposition.SOLE,
        [Member("s", "S")],
        institution=Institution.AD_HOC,
        regime=Regime.DOMESTIC,
        chair_requirement_waived=True,
    )
    assert "decisive_arbitrator_needs_law_degree" in sole.problems
    intl = check_tribunal(
        TribunalComposition.THREE,
        lacking,
        institution=Institution.AD_HOC,
        regime=Regime.INTERNATIONAL,
    )
    assert intl.ok


@pytest.mark.parametrize(
    ("amount", "currency", "advised"),
    [("5000000", "RUB", True), ("5000000.01", "RUB", False), ("100", "USD", False)],
)
def test_icac_sole_arbitrator_advisory(amount: str, currency: str, advised: bool) -> None:
    check = check_tribunal(
        TribunalComposition.THREE,
        members(3),
        institution=Institution.ICAC_MKAS,
        regime=Regime.DOMESTIC,
        claim_amount=Decimal(amount),
        claim_currency=currency,
    )
    assert ("icac_domestic_sole_arbitrator_default" in check.advisories) is advised


def test_member_from_dict_aliases() -> None:
    m = Member.from_dict({"id": "x", "arbitrator_name": "N", "law_degree": 1})
    assert (m.arbitrator_id, m.name, m.law_degree, m.is_chair) == ("x", "N", True, False)
