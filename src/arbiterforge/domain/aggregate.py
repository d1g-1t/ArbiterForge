from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from arbiterforge.domain.arbitrability import DisputeCategory, assess_arbitrability
from arbiterforge.domain.deadlines import compute_case_deadlines, parse_day
from arbiterforge.domain.events import EVENT_SCHEMA_VERSION, EventType
from arbiterforge.domain.exceptions import ConcurrencyError, InvalidTransitionError, ValidationError
from arbiterforge.domain.regime import RegimeInput, determine_regime
from arbiterforge.domain.state_machine import assert_transition_allowed, next_status
from arbiterforge.domain.tribunal import Member, check_tribunal
from arbiterforge.domain.value_objects import (
    AwardKind,
    CaseStatus,
    CorrectionKind,
    EventEnvelope,
    HearingFormat,
    Institution,
    Money,
    NominationSide,
    PartyRole,
    PartyType,
    Regime,
    SetAsideOutcome,
    TribunalComposition,
    is_valid_inn,
    is_valid_ogrn,
)

AGGREGATE_TYPE = "ArbitrationCase"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _enum[E: StrEnum](enum: type[E], value: Any, field_name: str) -> E:
    try:
        return enum(value)
    except ValueError:
        raise ValidationError(f"Invalid {field_name}: {value}") from None


def _day(value: Any, field_name: str) -> str:
    if value is None:
        return _today()
    try:
        parsed = parse_day(value)
    except ValueError:
        raise ValidationError(f"Invalid date in {field_name}: {value}") from None
    assert parsed is not None
    return parsed.isoformat()


@dataclass
class ArbitrationCaseState:
    aggregate_id: str
    organization_id: str | None = None
    version: int = 0
    status: CaseStatus | None = None
    institution: Institution | None = None
    regime: Regime | None = None
    seat: dict[str, str] | None = None
    language: str | None = None
    claim_amount: str | None = None
    claim_currency: str | None = None
    final_award_agreed: bool = False
    parties: list[dict[str, Any]] = field(default_factory=list)
    tribunal: dict[str, Any] = field(default_factory=dict)
    milestones: list[dict[str, Any]] = field(default_factory=list)
    submissions: list[dict[str, Any]] = field(default_factory=list)
    procedural_orders: list[dict[str, Any]] = field(default_factory=list)
    hearings: list[dict[str, Any]] = field(default_factory=list)
    award: dict[str, Any] | None = None
    award_receipts: dict[str, str] = field(default_factory=dict)
    history: list[EventEnvelope] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    payload: dict[str, Any]
    actor_id: str | None = None
    organization_id: str | None = None
    expected_version: int | None = None


Decider = Callable[["ArbitrationCaseAggregate", dict[str, Any]], tuple[EventType, dict[str, Any]]]


class ArbitrationCaseAggregate:
    AGGREGATE_TYPE = AGGREGATE_TYPE

    def __init__(self, state: ArbitrationCaseState | None = None) -> None:
        self.state = state or ArbitrationCaseState(aggregate_id=_new_id())

    @classmethod
    def from_history(
        cls, aggregate_id: str, events: list[EventEnvelope]
    ) -> ArbitrationCaseAggregate:
        agg = cls(ArbitrationCaseState(aggregate_id=aggregate_id))
        for ev in events:
            agg.apply(ev)
        return agg

    def party(self, party_id: str) -> dict[str, Any] | None:
        return next((p for p in self.state.parties if p.get("party_id") == party_id), None)

    def apply(self, ev: EventEnvelope) -> None:
        s = self.state
        p = ev.payload
        et = EventType(ev.event_type)
        s.status = (
            next_status(s.status, et) if et is not EventType.CASE_OPENED else CaseStatus.INTAKE
        )
        s.version = ev.version
        s.history.append(ev)
        match et:
            case EventType.CASE_OPENED:
                s.organization_id = p.get("organization_id") or ev.organization_id
                s.institution = Institution(p.get("institution", Institution.ICAC_MKAS))
                s.regime = Regime(p.get("regime", Regime.DOMESTIC))
                s.seat = p.get("seat")
                s.language = p.get("language")
                s.claim_amount = p.get("claim_amount")
                s.claim_currency = p.get("claim_currency", "RUB")
                s.final_award_agreed = bool(p.get("final_award_agreed", False))
                s.parties.extend(p.get("parties_draft") or [])
            case EventType.PARTY_ADDED:
                s.parties.append(p)
            case EventType.PARTY_UPDATED:
                for i, party in enumerate(s.parties):
                    if party.get("party_id") == p.get("party_id"):
                        s.parties[i] = {**party, **p}
            case EventType.ARBITRATOR_NOMINATED:
                s.tribunal.setdefault("nominations", []).append(p)
            case EventType.TRIBUNAL_CONSTITUTED:
                s.tribunal.update(p)
                s.tribunal["constituted"] = True
            case EventType.ARBITRATOR_REPLACED:
                members = s.tribunal.get("members") or []
                s.tribunal["members"] = [
                    p["replacement"] if m.get("arbitrator_id") == p["arbitrator_id"] else m
                    for m in members
                ]
            case EventType.PROCEDURAL_TIMETABLE_ADOPTED:
                s.milestones = [dict(m) for m in p.get("milestones") or []]
            case EventType.MILESTONE_EXTENDED:
                for m in s.milestones:
                    if m.get("code") == p.get("milestone_code"):
                        m["due_at"] = p.get("new_due_at")
                        m["extended_reason"] = p.get("reason")
            case EventType.SUBMISSION_FILED:
                s.submissions.append(p)
            case EventType.PROCEDURAL_ORDER_ISSUED:
                s.procedural_orders.append(p)
            case EventType.HEARING_SCHEDULED | EventType.HEARING_HELD | EventType.HEARING_ADJOURNED:
                s.hearings.append({**p, "event_type": et.value})
            case EventType.AWARD_DRAFTED | EventType.AWARD_ISSUED:
                s.award = p
            case EventType.AWARD_RECEIVED:
                s.award_receipts[p["party_id"]] = p["received_on"]
            case _:
                pass

    def _envelope(
        self, et: EventType, payload: dict[str, Any], actor: str | None, org: str | None
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=_new_id(),
            aggregate_id=self.state.aggregate_id,
            aggregate_type=AGGREGATE_TYPE,
            version=self.state.version + 1,
            event_type=et.value,
            payload=payload,
            occurred_at=_now_iso(),
            actor_id=actor,
            metadata={"schema_version": EVENT_SCHEMA_VERSION, "organization_id": org},
        )

    def decide(self, command: Command) -> list[EventEnvelope]:
        if command.expected_version is not None and command.expected_version != self.state.version:
            raise ConcurrencyError(
                self.state.aggregate_id, command.expected_version, self.state.version
            )
        decider = DECIDERS.get(command.name)
        if decider is None:
            raise ValidationError(f"Unknown command: {command.name}")
        payload = dict(command.payload)
        if command.name == "open_case":
            payload["organization_id"] = command.organization_id
        et, event_payload = decider(self, payload)
        assert_transition_allowed(self.state.status, et)
        org = command.organization_id or self.state.organization_id
        ev = self._envelope(et, event_payload, command.actor_id, org)
        self.apply(ev)
        return [ev]

    def deadlines(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in compute_case_deadlines(self.state.history)]


def _open_case(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    if agg.state.version != 0:
        raise InvalidTransitionError(
            str(agg.state.status), EventType.CASE_OPENED, "Case already opened"
        )
    institution = _enum(Institution, p.get("institution", Institution.ICAC_MKAS), "institution")
    category = _enum(DisputeCategory, p.get("dispute_category", "commercial"), "dispute_category")
    seat = p.get("seat") or {"city": "Moscow", "country": "RU"}
    claim_amount = p.get("claim_amount")
    currency = p.get("claim_currency", "RUB")
    if claim_amount is not None:
        try:
            Money(Decimal(str(claim_amount)), currency)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"Invalid claim amount: {exc}") from None
    decision = determine_regime(
        RegimeInput(
            seat_country=seat.get("country", "RU"),
            party_countries=tuple(p.get("party_countries") or ()),
            performance_abroad=bool(p.get("performance_abroad")),
            closest_connection_abroad=bool(p.get("closest_connection_abroad")),
            foreign_investment=bool(p.get("foreign_investment")),
        )
    )
    arbitrability = assess_arbitrability(
        category,
        institution,
        seat_country=seat.get("country", "RU"),
        regime=decision.regime,
        all_participants_signed=bool(p.get("all_participants_signed")),
        sanctions_involved=bool(p.get("sanctions_involved")),
    )
    if not arbitrability.admissible:
        raise ValidationError(
            "Dispute cannot be referred to this arbitration: " + ", ".join(arbitrability.problems),
            basis=arbitrability.basis,
        )
    final = bool(p.get("final_award_agreed"))
    excluded = bool(p.get("court_review_excluded"))
    if final and not institution.is_institutional:
        raise ValidationError(
            "Final award clause requires an arbitral institution", basis=("ICA_34_1", "DOM_40")
        )
    if excluded and not institution.is_institutional:
        raise ValidationError(
            "Exclusion of court review of challenges requires an arbitral institution",
            basis=("ICA_13_3",),
        )
    composition = _enum(
        TribunalComposition, p.get("agreed_composition", "three"), "agreed_composition"
    )
    return EventType.CASE_OPENED, {
        "organization_id": p.get("organization_id"),
        "title": p.get("title", "Arbitration case"),
        "institution": institution.value,
        "seat": seat,
        "language": p.get("language", "ru"),
        "claim_amount": None if claim_amount is None else str(claim_amount),
        "claim_currency": currency,
        "rules_edition": p.get("rules_edition"),
        "parties_draft": p.get("parties_draft") or [],
        "dispute_category": category.value,
        "agreed_composition": composition.value,
        "final_award_agreed": final,
        "court_review_excluded": excluded,
        "regime": decision.regime.value,
        "regime_reasons": list(decision.reasons),
        "applicable_law": decision.applicable_law,
        "arbitrability": arbitrability.to_dict(),
    }


def _file_case(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.CASE_FILED, {
        "filing_ref": p.get("filing_ref"),
        "filed_at": p.get("filed_at") or _now_iso(),
    }


def _register_rfa(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.REQUEST_FOR_ARBITRATION_REGISTERED, {
        "registered_at": p.get("registered_at") or _now_iso(),
        "received_on": _day(p.get("received_on"), "received_on"),
        "ref": p.get("ref"),
    }


def _add_party(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    role = _enum(PartyRole, p.get("role"), "role")
    party_type = _enum(PartyType, p.get("party_type", "legal_entity"), "party_type")
    if not p.get("name"):
        raise ValidationError("Party name is required")
    country = str(p.get("country") or "RU").upper()
    inn, ogrn = p.get("inn"), p.get("ogrn")
    if inn and country == "RU" and not is_valid_inn(inn):
        raise ValidationError(f"Invalid INN checksum: {inn}")
    if ogrn and country == "RU" and not is_valid_ogrn(ogrn):
        raise ValidationError(f"Invalid OGRN checksum: {ogrn}")
    return EventType.PARTY_ADDED, {
        "party_id": p.get("party_id") or _new_id(),
        "role": role.value,
        "party_type": party_type.value,
        "name": p["name"],
        "country": country,
        "inn": inn,
        "ogrn": ogrn,
        "counsel": p.get("counsel"),
    }


def _nominate(agg: ArbitrationCaseAggregate, p: dict[str, Any]) -> tuple[EventType, dict[str, Any]]:
    side = _enum(NominationSide, p.get("side"), "side")
    if not p.get("arbitrator_name"):
        raise ValidationError("Arbitrator name is required")
    return EventType.ARBITRATOR_NOMINATED, {
        "arbitrator_id": p.get("arbitrator_id") or _new_id(),
        "side": side.value,
        "arbitrator_name": p["arbitrator_name"],
        "law_degree": bool(p.get("law_degree", False)),
        "cv_ref": p.get("cv_ref"),
    }


def _constitute(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    composition = _enum(TribunalComposition, p.get("composition", "three"), "composition")
    chair_id = p.get("chair_id")
    raw = p.get("members") or [
        {
            "arbitrator_id": n["arbitrator_id"],
            "name": n["arbitrator_name"],
            "law_degree": n.get("law_degree", False),
        }
        for n in agg.state.tribunal.get("nominations", [])
    ]
    members = [Member.from_dict(m) for m in raw]
    if chair_id:
        members = [
            Member(m.arbitrator_id, m.name, m.law_degree, m.arbitrator_id == chair_id)
            for m in members
        ]
    elif len(members) == 1:
        members = [Member(members[0].arbitrator_id, members[0].name, members[0].law_degree, True)]
    amount = agg.state.claim_amount
    check = check_tribunal(
        composition,
        members,
        institution=agg.state.institution or Institution.ICAC_MKAS,
        regime=agg.state.regime or Regime.DOMESTIC,
        claim_amount=Decimal(amount) if amount else None,
        claim_currency=agg.state.claim_currency or "RUB",
        chair_requirement_waived=bool(p.get("chair_requirement_waived")),
    )
    if not check.ok:
        raise ValidationError(
            "Tribunal composition rejected: " + ", ".join(check.problems), basis=check.basis
        )
    chair = next((m.arbitrator_id for m in members if m.is_chair), None)
    return EventType.TRIBUNAL_CONSTITUTED, {
        "composition": composition.value,
        "chair_id": chair,
        "members": [
            {
                "arbitrator_id": m.arbitrator_id,
                "name": m.name,
                "law_degree": m.law_degree,
                "is_chair": m.is_chair,
            }
            for m in members
        ],
        "advisories": list(check.advisories),
        "basis": list(check.basis),
        "constituted_at": _day(p.get("constituted_at"), "constituted_at"),
    }


def _challenge(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    members = {m["arbitrator_id"] for m in agg.state.tribunal.get("members") or []}
    if p.get("arbitrator_id") not in members:
        raise ValidationError("Arbitrator is not a tribunal member")
    if not agg.party(str(p.get("party_id"))):
        raise ValidationError("Challenging party is not a party to the case")
    return EventType.ARBITRATOR_CHALLENGED, {
        "challenge_id": p.get("challenge_id") or _new_id(),
        "arbitrator_id": p["arbitrator_id"],
        "party_id": p["party_id"],
        "grounds": p.get("grounds", ""),
        "filed_on": _day(p.get("filed_on"), "filed_on"),
    }


def _decide_challenge(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    challenges = {
        e.payload["challenge_id"]: e.payload
        for e in agg.state.history
        if e.event_type == EventType.ARBITRATOR_CHALLENGED
    }
    challenge = challenges.get(p.get("challenge_id"))
    if challenge is None:
        raise ValidationError("Unknown challenge")
    return EventType.ARBITRATOR_CHALLENGE_DECIDED, {
        "challenge_id": challenge["challenge_id"],
        "arbitrator_id": challenge["arbitrator_id"],
        "challenging_party": challenge["party_id"],
        "upheld": bool(p.get("upheld")),
        "notified_on": _day(p.get("notified_on"), "notified_on"),
    }


def _replace_arbitrator(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    members = agg.state.tribunal.get("members") or []
    current = next((m for m in members if m["arbitrator_id"] == p.get("arbitrator_id")), None)
    if current is None:
        raise ValidationError("Arbitrator is not a tribunal member")
    replacement = {
        "arbitrator_id": p.get("replacement_id") or _new_id(),
        "name": p["replacement_name"],
        "law_degree": bool(p.get("law_degree", False)),
        "is_chair": current.get("is_chair", False),
    }
    return EventType.ARBITRATOR_REPLACED, {
        "arbitrator_id": current["arbitrator_id"],
        "replacement": replacement,
        "reason": p.get("reason"),
    }


def _rule_jurisdiction(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.JURISDICTION_RULED, {
        "has_jurisdiction": bool(p.get("has_jurisdiction", True)),
        "preliminary": bool(p.get("preliminary", True)),
        "notified_on": _day(p.get("notified_on"), "notified_on"),
        "reasoning": p.get("reasoning", ""),
    }


def _adopt_timetable(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    milestones = p.get("milestones") or []
    if not milestones:
        raise ValidationError("Timetable must include milestones")
    codes = [m.get("code") for m in milestones]
    if len(set(codes)) != len(codes):
        raise ValidationError("Milestone codes must be unique")
    return EventType.PROCEDURAL_TIMETABLE_ADOPTED, {
        "milestones": milestones,
        "adopted_at": p.get("adopted_at") or _now_iso(),
        "po_ref": p.get("po_ref"),
    }


def _extend_milestone(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    if not any(m.get("code") == p.get("milestone_code") for m in agg.state.milestones):
        raise ValidationError(f"Unknown milestone: {p.get('milestone_code')}")
    return EventType.MILESTONE_EXTENDED, {
        "milestone_code": p["milestone_code"],
        "new_due_at": p["new_due_at"],
        "reason": p.get("reason"),
    }


def _open_round(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.SUBMISSION_ROUND_OPENED, {
        "round_code": p["round_code"],
        "due_at": p.get("due_at"),
        "label": p.get("label"),
    }


def _file_submission(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.SUBMISSION_FILED, {
        "submission_id": p.get("submission_id") or _new_id(),
        "round_code": p.get("round_code"),
        "title": p["title"],
        "object_key": p.get("object_key"),
        "pages": p.get("pages"),
        "filed_at": p.get("filed_at") or _now_iso(),
    }


def _issue_po(agg: ArbitrationCaseAggregate, p: dict[str, Any]) -> tuple[EventType, dict[str, Any]]:
    return EventType.PROCEDURAL_ORDER_ISSUED, {
        "po_id": p.get("po_id") or _new_id(),
        "number": p["number"],
        "issued_at": p.get("issued_at") or _now_iso(),
        "gist": p.get("gist", ""),
        "requires_human_review": bool(p.get("requires_human_review", False)),
    }


def _schedule_hearing(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    fmt = _enum(HearingFormat, p.get("format", "remote"), "format")
    return EventType.HEARING_SCHEDULED, {
        "hearing_id": p.get("hearing_id") or _new_id(),
        "when": p["when"],
        "where": p.get("where"),
        "format": fmt.value,
    }


def _hearing_held(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.HEARING_HELD, {
        "hearing_id": p.get("hearing_id"),
        "held_at": p.get("held_at") or _now_iso(),
        "outcome_note": p.get("outcome_note"),
    }


def _start_deliberation(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.DELIBERATION_STARTED, {"started_at": p.get("started_at") or _now_iso()}


def _award_payload(p: dict[str, Any], stamp: str) -> dict[str, Any]:
    kind = _enum(AwardKind, p.get("kind", "final"), "kind")
    return {
        "kind": kind.value,
        "operative_summary": p.get("operative_summary", ""),
        stamp: p.get(stamp) or _now_iso(),
    }


def _draft_award(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.AWARD_DRAFTED, _award_payload(p, "drafted_at")


def _issue_award(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.AWARD_ISSUED, _award_payload(p, "issued_at")


def _receive_award(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    party_id = str(p.get("party_id"))
    if not agg.party(party_id):
        raise ValidationError("Unknown party")
    if party_id in agg.state.award_receipts:
        raise ValidationError("Receipt of the award already recorded for this party")
    return EventType.AWARD_RECEIVED, {
        "party_id": party_id,
        "received_on": _day(p.get("received_on"), "received_on"),
        "basis": ["ICA_33_1" if agg.state.regime is Regime.INTERNATIONAL else "DOM_37_1"],
    }


def _request_correction(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    party_id = str(p.get("party_id"))
    if party_id not in agg.state.award_receipts:
        raise ValidationError("Party has not received the award yet")
    kind = _enum(CorrectionKind, p.get("kind", "correction"), "kind")
    requested_on = _day(p.get("requested_on"), "requested_on")
    if date.fromisoformat(requested_on) < date.fromisoformat(agg.state.award_receipts[party_id]):
        raise ValidationError("Request predates receipt of the award")
    return EventType.CORRECTION_REQUESTED, {
        "request_id": p.get("request_id") or _new_id(),
        "party_id": party_id,
        "kind": kind.value,
        "requested_on": requested_on,
        "details": p.get("details", ""),
    }


def _decide_correction(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    requests = {
        e.payload["request_id"]: e.payload
        for e in agg.state.history
        if e.event_type == EventType.CORRECTION_REQUESTED
    }
    request = requests.get(p.get("request_id"))
    if request is None:
        raise ValidationError("Unknown correction request")
    return EventType.CORRECTION_DECIDED, {
        "request_id": request["request_id"],
        "kind": request["kind"],
        "granted": bool(p.get("granted", True)),
        "decided_on": _day(p.get("decided_on"), "decided_on"),
    }


def _file_set_aside(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    if agg.state.final_award_agreed:
        raise ValidationError(
            "Parties agreed the award is final; it is not subject to setting aside",
            basis=("ICA_34_1", "DOM_40"),
        )
    party_id = str(p.get("party_id"))
    if not agg.party(party_id):
        raise ValidationError("Unknown party")
    filed_on = _day(p.get("filed_on"), "filed_on")
    deadline = next(
        (
            d
            for d in compute_case_deadlines(agg.state.history)
            if d.code == "set_aside" and d.party == party_id
        ),
        None,
    )
    timely = None
    if deadline is not None and deadline.due_date is not None:
        timely = date.fromisoformat(filed_on) <= deadline.due_date
    return EventType.SET_ASIDE_NOTED, {
        "party_id": party_id,
        "court": p.get("court"),
        "filed_on": filed_on,
        "timely": timely,
        "due_date": deadline.due_date.isoformat() if deadline and deadline.due_date else None,
        "basis": ["APK_230_4"],
    }


def _resolve_set_aside(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    outcome = _enum(SetAsideOutcome, p.get("outcome"), "outcome")
    return EventType.CHALLENGE_RESOLVED, {
        "outcome": outcome.value,
        "resolved_on": _day(p.get("resolved_on"), "resolved_on"),
        "court_ref": p.get("court_ref"),
    }


def _close(agg: ArbitrationCaseAggregate, p: dict[str, Any]) -> tuple[EventType, dict[str, Any]]:
    return EventType.CASE_CLOSED, {"closed_at": p.get("closed_at") or _now_iso()}


def _terminate(
    agg: ArbitrationCaseAggregate, p: dict[str, Any]
) -> tuple[EventType, dict[str, Any]]:
    return EventType.CASE_TERMINATED, {
        "reason": p.get("reason", "terminated"),
        "terminated_at": p.get("terminated_at") or _now_iso(),
    }


DECIDERS: dict[str, Decider] = {
    "open_case": _open_case,
    "file_case": _file_case,
    "register_rfa": _register_rfa,
    "add_party": _add_party,
    "nominate_arbitrator": _nominate,
    "constitute_tribunal": _constitute,
    "challenge_arbitrator": _challenge,
    "decide_arbitrator_challenge": _decide_challenge,
    "replace_arbitrator": _replace_arbitrator,
    "rule_on_jurisdiction": _rule_jurisdiction,
    "adopt_timetable": _adopt_timetable,
    "extend_milestone": _extend_milestone,
    "open_submission_round": _open_round,
    "file_submission": _file_submission,
    "issue_procedural_order": _issue_po,
    "schedule_hearing": _schedule_hearing,
    "mark_hearing_held": _hearing_held,
    "start_deliberation": _start_deliberation,
    "draft_award": _draft_award,
    "issue_award": _issue_award,
    "receive_award": _receive_award,
    "request_correction": _request_correction,
    "decide_correction": _decide_correction,
    "file_set_aside": _file_set_aside,
    "resolve_set_aside": _resolve_set_aside,
    "close_case": _close,
    "terminate_case": _terminate,
}
