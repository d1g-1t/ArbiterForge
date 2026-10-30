from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property

from arbiterforge.domain.exceptions import CalendarCoverageError

HOLIDAYS_TK_112: tuple[tuple[int, int], ...] = (
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (1, 5),
    (1, 6),
    (1, 7),
    (1, 8),
    (2, 23),
    (3, 8),
    (5, 1),
    (5, 9),
    (6, 12),
    (11, 4),
)

GOVERNMENT_TRANSFERS: dict[int, tuple[tuple[date, date], ...]] = {
    2025: (
        (date(2025, 1, 4), date(2025, 5, 2)),
        (date(2025, 1, 5), date(2025, 12, 31)),
        (date(2025, 2, 23), date(2025, 5, 8)),
        (date(2025, 3, 8), date(2025, 6, 13)),
        (date(2025, 11, 1), date(2025, 11, 3)),
    ),
    2026: (
        (date(2026, 1, 3), date(2026, 1, 9)),
        (date(2026, 1, 4), date(2026, 12, 31)),
    ),
    2027: (
        (date(2027, 1, 2), date(2027, 11, 5)),
        (date(2027, 1, 3), date(2027, 12, 31)),
        (date(2027, 2, 20), date(2027, 2, 22)),
    ),
}

TRANSFER_ACTS: dict[int, str] = {
    2025: "Постановление Правительства РФ от 04.10.2024 № 1335",
    2026: "Постановление Правительства РФ от 24.09.2025 № 1466",
    2027: "Постановление Правительства РФ от 17.09.2026 № 1187",
}


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5


@dataclass(frozen=True)
class RussianWorkCalendar:
    transfers: dict[int, tuple[tuple[date, date], ...]] = field(
        default_factory=lambda: dict(GOVERNMENT_TRANSFERS)
    )

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted(self.transfers))

    @cached_property
    def _non_working(self) -> frozenset[date]:
        result: set[date] = set()
        for year in self.years:
            result |= self._year_non_working(year)
        return frozenset(result)

    def _year_non_working(self, year: int) -> set[date]:
        holidays = {date(year, m, d) for m, d in HOLIDAYS_TK_112}
        start = date(year, 1, 1)
        days = [start + timedelta(days=i) for i in range((date(year + 1, 1, 1) - start).days)]
        off = {d for d in days if _is_weekend(d)} | holidays
        sources = set()
        for source, target in self.transfers[year]:
            sources.add(source)
            off.add(target)
            if source not in holidays:
                off.discard(source)
        for holiday in sorted(holidays):
            if holiday.month == 1 or not _is_weekend(holiday) or holiday in sources:
                continue
            candidate = holiday + timedelta(days=1)
            while candidate in off:
                candidate += timedelta(days=1)
            off.add(candidate)
        return off

    def covers(self, day: date) -> bool:
        return day.year in self.transfers

    def _ensure(self, day: date) -> None:
        if not self.covers(day):
            raise CalendarCoverageError(day.year)

    def is_working_day(self, day: date) -> bool:
        self._ensure(day)
        return day not in self._non_working

    def next_working_day(self, day: date) -> date:
        candidate = day
        while not self.is_working_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def non_working_days(self, year: int) -> list[date]:
        self._ensure(date(year, 1, 1))
        return sorted(d for d in self._non_working if d.year == year)

    def working_days_between(self, start: date, end: date) -> int:
        count = 0
        day = start + timedelta(days=1)
        while day <= end:
            if self.is_working_day(day):
                count += 1
            day += timedelta(days=1)
        return count


DEFAULT_CALENDAR = RussianWorkCalendar()
