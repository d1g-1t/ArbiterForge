from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from arbiterforge.domain.aggregate import ArbitrationCaseAggregate
from arbiterforge.domain.deadlines import compute_case_deadlines
from arbiterforge.domain.events import EventType
from arbiterforge.domain.value_objects import EventEnvelope

DEADLINE_LABELS = {
    "respondent_nomination": "Назначение арбитра ответчиком",
    "arbitrator_challenge": "Заявление отвода арбитру",
    "court_challenge_review": "Обращение в суд после отклонения отвода",
    "court_jurisdiction_review": "Обращение в суд по вопросу компетенции",
    "correction_request": "Просьба об исправлении / толковании решения",
    "additional_award_request": "Просьба о дополнительном решении",
    "tribunal_correction_decision": "Решение третейского суда по исправлению",
    "tribunal_interpretation_decision": "Решение третейского суда по толкованию",
    "tribunal_additional_award_decision": "Вынесение дополнительного решения",
    "set_aside": "Заявление об отмене арбитражного решения",
    "case_file_storage": "Передача материалов дела на хранение",
}


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, UTC)
    raw = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class CaseProjection:
    status: dict[str, Any]
    tribunal: dict[str, Any]
    calendar: list[dict[str, Any]] = field(default_factory=list)


def build_case_projection(history: list[EventEnvelope]) -> CaseProjection:
    agg = ArbitrationCaseAggregate.from_history(history[0].aggregate_id, history)
    s = agg.state
    opened = history[0]
    op = opened.payload
    org = s.organization_id or ""
    status = {
        "case_id": s.aggregate_id,
        "organization_id": org,
        "current_status": s.status.value if s.status else "",
        "institution": s.institution.value if s.institution else None,
        "regime": s.regime.value if s.regime else None,
        "title": op.get("title"),
        "opened_at": parse_dt(opened.occurred_at),
        "last_event_at": parse_dt(history[-1].occurred_at),
        "version": s.version,
        "claim_amount": s.claim_amount,
        "claim_currency": s.claim_currency,
        "seat_city": (s.seat or {}).get("city"),
        "language": s.language,
        "extra": {
            "dispute_category": op.get("dispute_category"),
            "applicable_law": op.get("applicable_law"),
            "regime_reasons": op.get("regime_reasons", []),
            "final_award_agreed": s.final_award_agreed,
            "seat_country": (s.seat or {}).get("country"),
        },
    }
    t = s.tribunal
    tribunal = {
        "case_id": s.aggregate_id,
        "organization_id": org,
        "composition": t.get("composition"),
        "chair_id": t.get("chair_id"),
        "members": t.get("members") or [],
        "nominations": t.get("nominations") or [],
        "constituted": bool(t.get("constituted")),
        "constituted_at": parse_dt(t.get("constituted_at")),
        "version": s.version,
    }
    calendar: dict[str, dict[str, Any]] = {}

    def entry(key: str, kind: str, label: str, due: Any, extra: dict[str, Any]) -> None:
        calendar[key] = {
            "case_id": s.aggregate_id,
            "organization_id": org,
            "entry_key": key,
            "kind": kind,
            "label": label,
            "due_at": parse_dt(due),
            "completed_at": None,
            "extra": extra,
        }

    for m in s.milestones:
        entry(
            f"milestone:{m.get('code')}",
            "milestone",
            m.get("label") or m.get("code"),
            m.get("due_at"),
            {"code": m.get("code"), "extended_reason": m.get("extended_reason")},
        )
    for ev in history:
        p = ev.payload
        if ev.event_type == EventType.SUBMISSION_ROUND_OPENED:
            entry(
                f"round:{p.get('round_code')}",
                "submission_round",
                p.get("label") or p.get("round_code"),
                p.get("due_at"),
                {"round_code": p.get("round_code")},
            )
        elif ev.event_type == EventType.SUBMISSION_FILED and p.get("round_code"):
            row = calendar.get(f"round:{p['round_code']}")
            if row and row["completed_at"] is None:
                row["completed_at"] = parse_dt(p.get("filed_at") or ev.occurred_at)
        elif ev.event_type == EventType.HEARING_SCHEDULED:
            entry(
                f"hearing:{p.get('hearing_id') or ev.event_id}",
                "hearing",
                f"Hearing ({p.get('format', 'remote')})",
                p.get("when"),
                {"where": p.get("where"), "format": p.get("format")},
            )
        elif ev.event_type == EventType.HEARING_HELD:
            held = parse_dt(p.get("held_at") or ev.occurred_at)
            for key, row in calendar.items():
                if row["kind"] == "hearing" and row["completed_at"] is None:
                    hid = p.get("hearing_id")
                    if not hid or key == f"hearing:{hid}":
                        row["completed_at"] = held
    for d in compute_case_deadlines(history):
        data = d.to_dict()
        calendar[d.key] = {
            "case_id": s.aggregate_id,
            "organization_id": org,
            "entry_key": d.key,
            "kind": "statutory_deadline",
            "label": DEADLINE_LABELS.get(d.code, d.code),
            "due_at": parse_dt(d.due_date),
            "completed_at": parse_dt(d.completed_on),
            "extra": data,
        }
    return CaseProjection(status, tribunal, list(calendar.values()))
