from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbiterforge.domain.calendar import DEFAULT_CALENDAR as CAL
from arbiterforge.domain.calendar import RussianWorkCalendar
from arbiterforge.domain.exceptions import CalendarCoverageError

OFFICIAL_WEEKDAYS_OFF = {
    2025: [
        "2025-01-01",
        "2025-01-02",
        "2025-01-03",
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
        "2025-05-01",
        "2025-05-02",
        "2025-05-08",
        "2025-05-09",
        "2025-06-12",
        "2025-06-13",
        "2025-11-03",
        "2025-11-04",
        "2025-12-31",
    ],
    2026: [
        "2026-01-01",
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-02-23",
        "2026-03-09",
        "2026-05-01",
        "2026-05-11",
        "2026-06-12",
        "2026-11-04",
        "2026-12-31",
    ],
    2027: [
        "2027-01-01",
        "2027-01-04",
        "2027-01-05",
        "2027-01-06",
        "2027-01-07",
        "2027-01-08",
        "2027-02-22",
        "2027-02-23",
        "2027-03-08",
        "2027-05-03",
        "2027-05-10",
        "2027-06-14",
        "2027-11-04",
        "2027-11-05",
        "2027-12-31",
    ],
}
WORKING_SATURDAYS = {2025: ["2025-11-01"], 2026: [], 2027: ["2027-02-20"]}
TOTAL_NON_WORKING = {2025: 118, 2026: 118, 2027: 118}

days_in_coverage = st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 12, 31))


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_weekday_holidays_match_government_decrees(year: int) -> None:
    weekdays = [d.isoformat() for d in CAL.non_working_days(year) if d.weekday() < 5]
    assert weekdays == OFFICIAL_WEEKDAYS_OFF[year]


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_transferred_saturdays_are_working(year: int) -> None:
    for day in WORKING_SATURDAYS[year]:
        assert CAL.is_working_day(date.fromisoformat(day))


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_working_day_totals(year: int) -> None:
    assert len(CAL.non_working_days(year)) == TOTAL_NON_WORKING[year]


def test_outside_coverage_raises() -> None:
    with pytest.raises(CalendarCoverageError) as exc:
        CAL.is_working_day(date(2028, 1, 10))
    assert exc.value.year == 2028


def test_custom_calendar_without_transfers_shifts_weekend_holidays() -> None:
    cal = RussianWorkCalendar(transfers={2026: ()})
    assert not cal.is_working_day(date(2026, 3, 9))
    assert cal.is_working_day(date(2026, 1, 9))


@given(days_in_coverage)
def test_next_working_day_is_working_and_not_earlier(day: date) -> None:
    if day.year == 2027 and day >= date(2027, 12, 31):
        return
    nxt = CAL.next_working_day(day)
    assert nxt >= day
    assert CAL.is_working_day(nxt)
    assert all(not CAL.is_working_day(day + timedelta(n)) for n in range((nxt - day).days))


@given(days_in_coverage, st.integers(min_value=0, max_value=60))
def test_working_days_between_counts_only_working_days(start: date, span: int) -> None:
    end = min(start + timedelta(days=span), date(2027, 12, 31))
    expected = sum(
        CAL.is_working_day(start + timedelta(n)) for n in range(1, (end - start).days + 1)
    )
    assert CAL.working_days_between(start, end) == expected
