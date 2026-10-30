from __future__ import annotations

from arbiterforge.domain.events import EventType
from arbiterforge.domain.exceptions import InvalidTransitionError
from arbiterforge.domain.value_objects import CaseStatus

S = CaseStatus
_PRE_HEARING = frozenset(
    {
        S.INTAKE,
        S.FILED,
        S.TRIBUNAL_PENDING,
        S.TRIBUNAL_CONSTITUTED,
        S.TIMETABLE_SET,
        S.SUBMISSIONS_OPEN,
    }
)
_TRIBUNAL_ACTIVE = frozenset(
    {S.TRIBUNAL_CONSTITUTED, S.TIMETABLE_SET, S.SUBMISSIONS_OPEN, S.HEARING_SCHEDULED}
)
_POST_AWARD = frozenset({S.AWARD_ISSUED, S.SET_ASIDE_CHALLENGE})

ALLOWED: dict[EventType, frozenset[CaseStatus]] = {
    EventType.CASE_FILED: frozenset({S.INTAKE}),
    EventType.REQUEST_FOR_ARBITRATION_REGISTERED: frozenset({S.FILED}),
    EventType.PARTY_ADDED: _PRE_HEARING,
    EventType.PARTY_UPDATED: _PRE_HEARING | {S.HEARING_SCHEDULED},
    EventType.ARBITRATOR_NOMINATED: frozenset({S.TRIBUNAL_PENDING, S.TRIBUNAL_CONSTITUTED}),
    EventType.ARBITRATOR_ACCEPTED: frozenset({S.TRIBUNAL_PENDING, S.TRIBUNAL_CONSTITUTED}),
    EventType.ARBITRATOR_CHALLENGED: _TRIBUNAL_ACTIVE,
    EventType.ARBITRATOR_CHALLENGE_DECIDED: _TRIBUNAL_ACTIVE,
    EventType.ARBITRATOR_REPLACED: _TRIBUNAL_ACTIVE,
    EventType.TRIBUNAL_CONSTITUTED: frozenset({S.TRIBUNAL_PENDING}),
    EventType.JURISDICTION_RULED: frozenset(
        {S.TRIBUNAL_CONSTITUTED, S.TIMETABLE_SET, S.SUBMISSIONS_OPEN}
    ),
    EventType.PROCEDURAL_TIMETABLE_ADOPTED: frozenset({S.TRIBUNAL_CONSTITUTED}),
    EventType.MILESTONE_EXTENDED: frozenset(
        {S.TIMETABLE_SET, S.SUBMISSIONS_OPEN, S.HEARING_SCHEDULED}
    ),
    EventType.SUBMISSION_ROUND_OPENED: frozenset({S.TIMETABLE_SET, S.SUBMISSIONS_OPEN}),
    EventType.SUBMISSION_FILED: frozenset({S.SUBMISSIONS_OPEN, S.HEARING_SCHEDULED}),
    EventType.PROCEDURAL_ORDER_ISSUED: _TRIBUNAL_ACTIVE | {S.HEARING_HELD, S.DELIBERATION},
    EventType.HEARING_SCHEDULED: frozenset({S.SUBMISSIONS_OPEN, S.TIMETABLE_SET}),
    EventType.HEARING_HELD: frozenset({S.HEARING_SCHEDULED}),
    EventType.HEARING_ADJOURNED: frozenset({S.HEARING_SCHEDULED}),
    EventType.DOCUMENTS_ONLY_CLOSED: frozenset({S.SUBMISSIONS_OPEN}),
    EventType.DELIBERATION_STARTED: frozenset({S.HEARING_HELD, S.SUBMISSIONS_OPEN}),
    EventType.AWARD_DRAFTED: frozenset({S.DELIBERATION}),
    EventType.AWARD_ISSUED: frozenset({S.AWARD_DRAFT, S.DELIBERATION}),
    EventType.AWARD_RECEIVED: _POST_AWARD,
    EventType.CORRECTION_REQUESTED: _POST_AWARD,
    EventType.CORRECTION_DECIDED: _POST_AWARD,
    EventType.SET_ASIDE_NOTED: _POST_AWARD,
    EventType.CHALLENGE_RESOLVED: frozenset({S.SET_ASIDE_CHALLENGE}),
    EventType.CASE_CLOSED: _POST_AWARD,
    EventType.CASE_TERMINATED: frozenset(
        {
            S.FILED,
            S.TRIBUNAL_PENDING,
            S.TRIBUNAL_CONSTITUTED,
            S.TIMETABLE_SET,
            S.SUBMISSIONS_OPEN,
            S.HEARING_SCHEDULED,
            S.HEARING_HELD,
            S.DELIBERATION,
        }
    ),
}

NEXT_STATUS: dict[EventType, CaseStatus] = {
    EventType.CASE_OPENED: S.INTAKE,
    EventType.CASE_FILED: S.FILED,
    EventType.REQUEST_FOR_ARBITRATION_REGISTERED: S.TRIBUNAL_PENDING,
    EventType.TRIBUNAL_CONSTITUTED: S.TRIBUNAL_CONSTITUTED,
    EventType.PROCEDURAL_TIMETABLE_ADOPTED: S.TIMETABLE_SET,
    EventType.SUBMISSION_ROUND_OPENED: S.SUBMISSIONS_OPEN,
    EventType.HEARING_SCHEDULED: S.HEARING_SCHEDULED,
    EventType.HEARING_HELD: S.HEARING_HELD,
    EventType.HEARING_ADJOURNED: S.SUBMISSIONS_OPEN,
    EventType.DOCUMENTS_ONLY_CLOSED: S.DELIBERATION,
    EventType.DELIBERATION_STARTED: S.DELIBERATION,
    EventType.AWARD_DRAFTED: S.AWARD_DRAFT,
    EventType.AWARD_ISSUED: S.AWARD_ISSUED,
    EventType.SET_ASIDE_NOTED: S.SET_ASIDE_CHALLENGE,
    EventType.CHALLENGE_RESOLVED: S.CLOSED,
    EventType.CASE_CLOSED: S.CLOSED,
    EventType.CASE_TERMINATED: S.TERMINATED,
}


def assert_transition_allowed(current: CaseStatus | None, event_type: str) -> None:
    if event_type == EventType.CASE_OPENED:
        if current is not None:
            raise InvalidTransitionError(
                str(current), event_type, "CaseOpened only allowed on empty aggregate"
            )
        return
    if current is None:
        raise InvalidTransitionError("None", event_type, "Aggregate has no CaseOpened yet")
    try:
        allowed = ALLOWED[EventType(event_type)]
    except ValueError:
        raise InvalidTransitionError(
            str(current), event_type, f"Unknown event type {event_type}"
        ) from None
    if current not in allowed:
        raise InvalidTransitionError(str(current), event_type)


def next_status(current: CaseStatus | None, event_type: str) -> CaseStatus:
    assert_transition_allowed(current, event_type)
    nxt = NEXT_STATUS.get(EventType(event_type))
    if nxt is not None:
        return nxt
    assert current is not None
    return current
