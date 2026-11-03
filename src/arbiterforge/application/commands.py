from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.domain.aggregate import ArbitrationCaseAggregate, Command
from arbiterforge.domain.events import EventType
from arbiterforge.domain.exceptions import ConcurrencyError, NotFoundError, ValidationError
from arbiterforge.domain.value_objects import EventEnvelope
from arbiterforge.infrastructure.audit_store import AuditStore
from arbiterforge.infrastructure.db.models import ProceduralOrderModel
from arbiterforge.infrastructure.event_store.postgres import PostgresEventStore
from arbiterforge.infrastructure.projections.builder import parse_dt
from arbiterforge.infrastructure.projections.store import ProjectionStore

AUDITED_EVENTS = frozenset(
    {
        EventType.TRIBUNAL_CONSTITUTED,
        EventType.ARBITRATOR_CHALLENGE_DECIDED,
        EventType.JURISDICTION_RULED,
        EventType.PROCEDURAL_ORDER_ISSUED,
        EventType.AWARD_ISSUED,
        EventType.CORRECTION_DECIDED,
        EventType.SET_ASIDE_NOTED,
        EventType.CASE_TERMINATED,
    }
)


class CaseCommandService:
    def __init__(self, session: AsyncSession, audit_secret: bytes) -> None:
        self._session = session
        self._store = PostgresEventStore(session)
        self._audit = AuditStore(session, audit_secret)

    async def load(self, case_id: str, organization_id: str) -> ArbitrationCaseAggregate:
        history = await self._store.load_stream(case_id)
        if not history:
            raise NotFoundError("ArbitrationCase", case_id)
        agg = ArbitrationCaseAggregate.from_history(case_id, history)
        if agg.state.organization_id != organization_id:
            raise NotFoundError("ArbitrationCase", case_id)
        return agg

    async def execute(
        self,
        *,
        case_id: str | None,
        command_name: str,
        payload: dict[str, Any],
        actor_id: str,
        organization_id: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        if command_name == "open_case":
            agg = ArbitrationCaseAggregate()
        elif case_id is None:
            raise ValidationError("case_id is required")
        else:
            agg = await self.load(case_id, organization_id)
        current = agg.state.version
        if expected_version is not None and expected_version != current:
            raise ConcurrencyError(agg.state.aggregate_id, expected_version, current)
        events = agg.decide(
            Command(command_name, payload, actor_id=actor_id, organization_id=organization_id)
        )
        await self._store.append(events, expected_version=current)
        await ProjectionStore(self._session).refresh_case(agg.state.aggregate_id)
        for ev in events:
            await self._after_append(ev, actor_id, organization_id)
        await self._session.flush()
        return {
            "case_id": agg.state.aggregate_id,
            "version": agg.state.version,
            "events": [e.to_dict() for e in events],
            "current_status": agg.state.status.value if agg.state.status else None,
        }

    async def _after_append(self, ev: EventEnvelope, actor_id: str, organization_id: str) -> None:
        p = ev.payload
        if ev.event_type == EventType.PROCEDURAL_ORDER_ISSUED:
            self._session.add(
                ProceduralOrderModel(
                    id=p["po_id"],
                    case_id=ev.aggregate_id,
                    organization_id=organization_id,
                    number=p.get("number", ""),
                    issued_at=parse_dt(p.get("issued_at")) or datetime.now(UTC),
                    gist=p.get("gist") or "",
                    requires_human_review=bool(p.get("requires_human_review")),
                    content_hash=hashlib.sha256((p.get("gist") or "").encode()).hexdigest(),
                )
            )
        if ev.event_type in AUDITED_EVENTS:
            await self._audit.append(
                organization_id=organization_id,
                actor_id=actor_id,
                action=ev.event_type,
                entity_type=ev.aggregate_type,
                entity_id=ev.aggregate_id,
                payload={"version": ev.version, "event_id": ev.event_id, "payload": p},
            )

    async def accept_po_summary(
        self, po_id: str, *, actor_id: str, organization_id: str
    ) -> ProceduralOrderModel:
        po = await self._session.get(ProceduralOrderModel, po_id, with_for_update=True)
        if po is None or po.organization_id != organization_id:
            raise NotFoundError("ProceduralOrder", po_id)
        if not po.ai_summary_draft:
            raise ValidationError("No AI draft to accept")
        if not po.human_accepted:
            po.human_accepted = True
            po.accepted_by = actor_id
            po.accepted_at = datetime.now(UTC)
            await self._audit.append(
                organization_id=organization_id,
                actor_id=actor_id,
                action="ProceduralOrderSummaryAccepted",
                entity_type="ProceduralOrder",
                entity_id=po.id,
                payload={
                    "case_id": po.case_id,
                    "summary_sha256": hashlib.sha256(po.ai_summary_draft.encode()).hexdigest(),
                },
            )
        return po
