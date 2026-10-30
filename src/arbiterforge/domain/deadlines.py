from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from arbiterforge.domain.calendar import DEFAULT_CALENDAR, RussianWorkCalendar
from arbiterforge.domain.events import EventType
from arbiterforge.domain.exceptions import CalendarCoverageError
from arbiterforge.domain.terms import ComputationRule, TermSpec, TermUnit, compute_deadline
from arbiterforge.domain.value_objects import CorrectionKind, EventEnvelope, Institution, Regime

TRIBUNAL = "tribunal"

THIRTY_DAYS = TermSpec(30, TermUnit.DAYS, ComputationRule.CIVIL)
SIXTY_DAYS = TermSpec(60, TermUnit.DAYS, ComputationRule.CIVIL)
FIFTEEN_DAYS = TermSpec(15, TermUnit.DAYS, ComputationRule.CIVIL)
ONE_MONTH = TermSpec(1, TermUnit.MONTHS, ComputationRule.CIVIL)
THREE_MONTHS_APK = TermSpec(3, TermUnit.MONTHS, ComputationRule.APK)


@dataclass(frozen=True, slots=True)
class Deadline:
    code: str
    party: str
    trigger_date: date
    due_date: date | None
    term: TermSpec
    basis: tuple[str, ...]
    dispositive: bool
    completed_on: date | None = None
    note: str | None = None

    @property
    def key(self) -> str:
        return f"deadline:{self.code}:{self.party}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "code": self.code,
            "party": self.party,
            "trigger_date": self.trigger_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "term": {
                "amount": self.term.amount,
                "unit": self.term.unit.value,
                "rule": self.term.rule.value,
            },
            "basis": list(self.basis),
            "dispositive": self.dispositive,
            "completed_on": self.completed_on.isoformat() if self.completed_on else None,
            "note": self.note,
        }


def parse_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def make_deadline(
    code: str,
    party: str,
    trigger: date,
    term: TermSpec,
    basis: tuple[str, ...],
    *,
    dispositive: bool,
    cal: RussianWorkCalendar = DEFAULT_CALENDAR,
) -> Deadline:
    try:
        due: date | None = compute_deadline(trigger, term, cal)
        note = None
    except CalendarCoverageError as exc:
        due = None
        note = f"calendar_not_covered:{exc.year}"
    return Deadline(code, party, trigger, due, term, basis, dispositive, note=note)


@dataclass
class _CaseFacts:
    institution: Institution = Institution.ICAC_MKAS
    regime: Regime = Regime.DOMESTIC
    final_award_agreed: bool = False
    court_review_excluded: bool = False
    composition: str = "three"


def _law(facts: _CaseFacts, intl: str, dom: str) -> str:
    return intl if facts.regime is Regime.INTERNATIONAL else dom


def compute_case_deadlines(
    events: Iterable[EventEnvelope], cal: RussianWorkCalendar = DEFAULT_CALENDAR
) -> list[Deadline]:
    facts = _CaseFacts()
    found: dict[str, Deadline] = {}
    award_receipts: dict[str, date] = {}

    def put(d: Deadline) -> None:
        found[d.key] = d

    def complete(key: str, day: date | None) -> None:
        if key in found and day is not None and found[key].completed_on is None:
            found[key] = replace(found[key], completed_on=day)

    for ev in events:
        p = ev.payload
        et = ev.event_type
        if et == EventType.CASE_OPENED:
            facts = _CaseFacts(
                institution=Institution(p.get("institution", Institution.ICAC_MKAS)),
                regime=Regime(p.get("regime", Regime.DOMESTIC)),
                final_award_agreed=bool(p.get("final_award_agreed", False)),
                court_review_excluded=bool(p.get("court_review_excluded", False)),
                composition=str(p.get("agreed_composition", "three")),
            )
            continue
        if facts.regime is Regime.FOREIGN_SEAT:
            continue
        intl = facts.regime is Regime.INTERNATIONAL
        if et == EventType.REQUEST_FOR_ARBITRATION_REGISTERED:
            day = parse_day(p.get("received_on") or p.get("registered_at"))
            if day and facts.institution is Institution.AD_HOC and facts.composition != "sole":
                put(
                    make_deadline(
                        "respondent_nomination",
                        "respondent",
                        day,
                        THIRTY_DAYS if intl else ONE_MONTH,
                        (_law(facts, "ICA_11_3", "DOM_11_3"),),
                        dispositive=True,
                        cal=cal,
                    )
                )
        elif et == EventType.ARBITRATOR_NOMINATED and p.get("side") == "respondent":
            complete("deadline:respondent_nomination:respondent", parse_day(ev.occurred_at))
        elif et == EventType.TRIBUNAL_CONSTITUTED:
            day = parse_day(p.get("constituted_at"))
            if day:
                put(
                    make_deadline(
                        "arbitrator_challenge",
                        "any",
                        day,
                        FIFTEEN_DAYS,
                        (_law(facts, "ICA_13_2", "DOM_13_2"),),
                        dispositive=True,
                        cal=cal,
                    )
                )
        elif et == EventType.ARBITRATOR_CHALLENGED:
            complete("deadline:arbitrator_challenge:any", parse_day(p.get("filed_on")))
        elif et == EventType.ARBITRATOR_CHALLENGE_DECIDED:
            day = parse_day(p.get("notified_on"))
            excluded = intl and facts.institution.is_institutional and facts.court_review_excluded
            if day and not p.get("upheld") and not excluded:
                put(
                    make_deadline(
                        "court_challenge_review",
                        str(p.get("challenging_party") or "any"),
                        day,
                        ONE_MONTH,
                        (_law(facts, "ICA_13_3", "DOM_13_3"),),
                        dispositive=False,
                        cal=cal,
                    )
                )
        elif et == EventType.JURISDICTION_RULED:
            day = parse_day(p.get("notified_on"))
            if day and p.get("has_jurisdiction"):
                put(
                    make_deadline(
                        "court_jurisdiction_review",
                        "any",
                        day,
                        ONE_MONTH,
                        (_law(facts, "ICA_16_3", "DOM_16_3"),),
                        dispositive=False,
                        cal=cal,
                    )
                )
        elif et == EventType.AWARD_RECEIVED:
            party = str(p["party_id"])
            day = parse_day(p.get("received_on"))
            if day is None:
                continue
            award_receipts[party] = day
            put(
                make_deadline(
                    "correction_request",
                    party,
                    day,
                    THIRTY_DAYS,
                    (_law(facts, "ICA_33_1", "DOM_37_1"),),
                    dispositive=True,
                    cal=cal,
                )
            )
            put(
                make_deadline(
                    "additional_award_request",
                    party,
                    day,
                    THIRTY_DAYS,
                    (_law(facts, "ICA_33_3", "DOM_37_4"),),
                    dispositive=True,
                    cal=cal,
                )
            )
            if not (facts.final_award_agreed and facts.institution.is_institutional):
                put(
                    make_deadline(
                        "set_aside",
                        party,
                        day,
                        THREE_MONTHS_APK,
                        ("ICA_34_3", "APK_230_4") if intl else ("APK_230_4",),
                        dispositive=False,
                        cal=cal,
                    )
                )
        elif et == EventType.CORRECTION_REQUESTED:
            day = parse_day(p.get("requested_on"))
            kind = CorrectionKind(p.get("kind", CorrectionKind.CORRECTION))
            party = str(p.get("party_id") or "any")
            if day:
                additional = kind is CorrectionKind.ADDITIONAL_AWARD
                code = "additional_award_request" if additional else "correction_request"
                complete(f"deadline:{code}:{party}", day)
                put(
                    make_deadline(
                        f"tribunal_{kind.value}_decision",
                        TRIBUNAL,
                        day,
                        SIXTY_DAYS if additional else THIRTY_DAYS,
                        (
                            _law(facts, "ICA_33_3", "DOM_37_4")
                            if additional
                            else _law(facts, "ICA_33_1", "DOM_37_1"),
                        ),
                        dispositive=False,
                        cal=cal,
                    )
                )
        elif et == EventType.CORRECTION_DECIDED:
            day = parse_day(p.get("decided_on"))
            kind = CorrectionKind(p.get("kind", CorrectionKind.CORRECTION))
            complete(f"deadline:tribunal_{kind.value}_decision:{TRIBUNAL}", day)
            if day and intl:
                for party in award_receipts:
                    key = f"deadline:set_aside:{party}"
                    if key in found and found[key].completed_on is None:
                        recomputed = make_deadline(
                            "set_aside",
                            party,
                            day,
                            THREE_MONTHS_APK,
                            ("ICA_34_3", "APK_230_4"),
                            dispositive=False,
                            cal=cal,
                        )
                        put(replace(recomputed, note=recomputed.note or "recomputed_after_art33"))
        elif et == EventType.SET_ASIDE_NOTED:
            complete(
                f"deadline:set_aside:{p.get('party_id') or 'any'}", parse_day(p.get("filed_on"))
            )
        elif et in (EventType.CASE_CLOSED, EventType.CASE_TERMINATED) and not intl:
            day = parse_day(p.get("closed_at") or p.get("terminated_at"))
            if day:
                put(
                    make_deadline(
                        "case_file_storage",
                        TRIBUNAL,
                        day,
                        ONE_MONTH,
                        ("DOM_39_1",),
                        dispositive=False,
                        cal=cal,
                    )
                )
    return sorted(found.values(), key=lambda d: (d.due_date or date.max, d.key))
