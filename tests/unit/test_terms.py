from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from arbiterforge.domain.calendar import DEFAULT_CALENDAR as CAL
from arbiterforge.domain.terms import (
    ComputationRule,
    TermSpec,
    TermUnit,
    add_months,
    apk_deadline,
    civil_deadline,
    compute_deadline,
)

starts = st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 6, 30))


@pytest.mark.parametrize(
    ("start", "spec", "expected"),
    [
        ("2026-12-25", TermSpec(5, TermUnit.DAYS, ComputationRule.APK), "2027-01-12"),
        ("2026-10-01", TermSpec(30, TermUnit.DAYS, ComputationRule.CIVIL), "2026-11-02"),
        ("2026-10-01", TermSpec(3, TermUnit.MONTHS, ComputationRule.APK), "2027-01-11"),
        ("2026-08-20", TermSpec(1, TermUnit.MONTHS, ComputationRule.CIVIL), "2026-09-21"),
        ("2026-01-31", TermSpec(1, TermUnit.MONTHS, ComputationRule.CIVIL), "2026-03-02"),
        ("2027-01-31", TermSpec(1, TermUnit.MONTHS, ComputationRule.APK), "2027-03-01"),
        ("2026-03-06", TermSpec(15, TermUnit.DAYS, ComputationRule.CIVIL), "2026-03-23"),
        ("2025-04-30", TermSpec(1, TermUnit.DAYS, ComputationRule.APK), "2025-05-05"),
    ],
)
def test_known_deadlines(start: str, spec: TermSpec, expected: str) -> None:
    assert compute_deadline(date.fromisoformat(start), spec).isoformat() == expected


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_non_positive_term_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        apk_deadline(date(2026, 1, 12), TermSpec(0, TermUnit.DAYS, ComputationRule.APK))
    with pytest.raises(ValueError, match="positive"):
        civil_deadline(date(2026, 1, 12), TermSpec(-1, TermUnit.MONTHS, ComputationRule.CIVIL))


@given(starts, st.integers(min_value=1, max_value=60), st.sampled_from(list(ComputationRule)))
def test_day_term_ends_on_working_day_after_start(
    start: date, days: int, rule: ComputationRule
) -> None:
    due = compute_deadline(start, TermSpec(days, TermUnit.DAYS, rule))
    assert due > start
    assert CAL.is_working_day(due)


@given(starts, st.integers(min_value=1, max_value=60))
def test_apk_day_term_counts_exactly_n_working_days(start: date, days: int) -> None:
    due = apk_deadline(start, TermSpec(days, TermUnit.DAYS, ComputationRule.APK))
    assert CAL.working_days_between(start, due) == days


@given(starts, st.integers(min_value=1, max_value=60))
def test_civil_day_term_never_shorter_than_calendar_days(start: date, days: int) -> None:
    due = civil_deadline(start, TermSpec(days, TermUnit.DAYS, ComputationRule.CIVIL))
    assert due >= start + timedelta(days=days)
    nominal = start + timedelta(days=days)
    if CAL.is_working_day(nominal):
        assert due == nominal


@given(starts, st.integers(min_value=1, max_value=59))
def test_terms_are_monotonic_in_length(start: date, days: int) -> None:
    for rule in ComputationRule:
        shorter = compute_deadline(start, TermSpec(days, TermUnit.DAYS, rule))
        longer = compute_deadline(start, TermSpec(days + 1, TermUnit.DAYS, rule))
        assert longer >= shorter


@given(starts, st.integers(min_value=1, max_value=6))
def test_month_terms_agree_between_regimes(start: date, months: int) -> None:
    apk = compute_deadline(start, TermSpec(months, TermUnit.MONTHS, ComputationRule.APK))
    civil = compute_deadline(start, TermSpec(months, TermUnit.MONTHS, ComputationRule.CIVIL))
    assert apk == civil
    nominal = add_months(start, months)
    assert apk >= nominal
    assert CAL.is_working_day(apk)


@given(starts, st.integers(min_value=1, max_value=6))
def test_month_term_lands_in_expected_month_unless_shifted(start: date, months: int) -> None:
    nominal = add_months(start, months)
    assume(CAL.is_working_day(nominal))
    assert (
        compute_deadline(start, TermSpec(months, TermUnit.MONTHS, ComputationRule.APK)) == nominal
    )
    assert nominal.day <= start.day
