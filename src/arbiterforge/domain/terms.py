from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from arbiterforge.domain.calendar import DEFAULT_CALENDAR, RussianWorkCalendar


class TermUnit(StrEnum):
    DAYS = "days"
    MONTHS = "months"


class ComputationRule(StrEnum):
    APK = "APK_113_114"
    CIVIL = "GK_191_193"


@dataclass(frozen=True, slots=True)
class TermSpec:
    amount: int
    unit: TermUnit
    rule: ComputationRule


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, _cal.monthrange(year, month)[1])
    return date(year, month, day)


def apk_deadline(
    event_day: date, spec: TermSpec, cal: RussianWorkCalendar = DEFAULT_CALENDAR
) -> date:
    if spec.amount <= 0:
        raise ValueError("Term must be positive")
    if spec.unit is TermUnit.MONTHS:
        return cal.next_working_day(add_months(event_day, spec.amount))
    remaining = spec.amount
    day = event_day
    while remaining:
        day += timedelta(days=1)
        if cal.is_working_day(day):
            remaining -= 1
    return day


def civil_deadline(
    event_day: date, spec: TermSpec, cal: RussianWorkCalendar = DEFAULT_CALENDAR
) -> date:
    if spec.amount <= 0:
        raise ValueError("Term must be positive")
    if spec.unit is TermUnit.MONTHS:
        last = add_months(event_day, spec.amount)
    else:
        last = event_day + timedelta(days=spec.amount)
    return cal.next_working_day(last)


def compute_deadline(
    event_day: date, spec: TermSpec, cal: RussianWorkCalendar = DEFAULT_CALENDAR
) -> date:
    if spec.rule is ComputationRule.APK:
        return apk_deadline(event_day, spec, cal)
    return civil_deadline(event_day, spec, cal)
