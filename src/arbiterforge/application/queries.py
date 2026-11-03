from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.domain.exceptions import NotFoundError
from arbiterforge.domain.value_objects import EventEnvelope
from arbiterforge.infrastructure.db.models import (
    CalendarProjectionModel,
    CaseStatusProjectionModel,
    TribunalProjectionModel,
)
from arbiterforge.infrastructure.event_store.postgres import PostgresEventStore


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _summary(r: CaseStatusProjectionModel) -> dict[str, Any]:
    return {
        "case_id": r.case_id,
        "organization_id": r.organization_id,
        "current_status": r.current_status,
        "institution": r.institution,
        "regime": r.regime,
        "title": r.title,
        "version": r.version,
        "opened_at": _iso(r.opened_at),
        "last_event_at": _iso(r.last_event_at),
    }


def _calendar_row(r: CalendarProjectionModel) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "kind": r.kind,
        "label": r.label,
        "entry_key": r.entry_key,
        "due_at": _iso(r.due_at),
        "completed_at": _iso(r.completed_at),
    }


class CaseQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._store = PostgresEventStore(session)

    async def _status_row(self, case_id: str, org_id: str) -> CaseStatusProjectionModel:
        result = await self._session.execute(
            select(CaseStatusProjectionModel).where(
                CaseStatusProjectionModel.case_id == case_id,
                CaseStatusProjectionModel.organization_id == org_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("ArbitrationCase", case_id)
        return row

    async def list_cases(self, org_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(CaseStatusProjectionModel)
            .where(CaseStatusProjectionModel.organization_id == org_id)
            .order_by(CaseStatusProjectionModel.last_event_at.desc())
        )
        return [_summary(r) for r in result.scalars()]

    async def get_case(self, case_id: str, org_id: str) -> dict[str, Any]:
        r = await self._status_row(case_id, org_id)
        events = await self._store.load_stream(case_id)
        return {
            **_summary(r),
            "claim_amount": r.claim_amount,
            "claim_currency": r.claim_currency,
            "seat_city": r.seat_city,
            "language": r.language,
            "legal": r.extra,
            "recent_timeline": [e.to_dict() for e in events[-20:]],
        }

    async def events(self, case_id: str, org_id: str) -> list[EventEnvelope]:
        await self._status_row(case_id, org_id)
        return await self._store.load_stream(case_id)

    async def timeline(self, case_id: str, org_id: str) -> list[dict[str, Any]]:
        return [e.to_dict() for e in await self.events(case_id, org_id)]

    async def tribunal(self, case_id: str, org_id: str) -> dict[str, Any]:
        await self._status_row(case_id, org_id)
        r = await self._session.get(TribunalProjectionModel, case_id)
        if r is None:
            return {"case_id": case_id, "constituted": False, "nominations": [], "members": []}
        return {
            "case_id": r.case_id,
            "composition": r.composition,
            "chair_id": r.chair_id,
            "members": r.members,
            "nominations": r.nominations,
            "constituted": r.constituted,
            "constituted_at": _iso(r.constituted_at),
            "version": r.version,
        }

    async def calendar(
        self,
        org_id: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(CalendarProjectionModel).where(
            CalendarProjectionModel.organization_id == org_id
        )
        if date_from:
            stmt = stmt.where(CalendarProjectionModel.due_at >= date_from)
        if date_to:
            stmt = stmt.where(CalendarProjectionModel.due_at <= date_to)
        if kind:
            stmt = stmt.where(CalendarProjectionModel.kind == kind)
        stmt = stmt.order_by(CalendarProjectionModel.due_at.asc().nulls_last())
        result = await self._session.execute(stmt)
        return [_calendar_row(r) for r in result.scalars()]

    async def deadlines(self, case_id: str, org_id: str) -> list[dict[str, Any]]:
        await self._status_row(case_id, org_id)
        result = await self._session.execute(
            select(CalendarProjectionModel)
            .where(
                CalendarProjectionModel.case_id == case_id,
                CalendarProjectionModel.kind == "statutory_deadline",
            )
            .order_by(CalendarProjectionModel.due_at.asc().nulls_last())
        )
        return [{**r.extra, "label": r.label} for r in result.scalars()]
