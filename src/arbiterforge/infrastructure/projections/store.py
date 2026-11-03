from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.infrastructure.db.models import (
    CalendarProjectionModel,
    CaseStatusProjectionModel,
    TribunalProjectionModel,
)
from arbiterforge.infrastructure.event_store.postgres import REBUILD_LOCK_KEY, PostgresEventStore
from arbiterforge.infrastructure.projections.builder import build_case_projection


async def _guarded_upsert(session: AsyncSession, model: Any, row: dict[str, Any]) -> bool:
    stmt = insert(model).values(**row)
    updates = {k: stmt.excluded[k] for k in row if k != "case_id"}
    stmt = stmt.on_conflict_do_update(
        index_elements=["case_id"],
        set_=updates,
        where=model.__table__.c.version < stmt.excluded.version,
    ).returning(model.__table__.c.case_id)
    result = await session.execute(stmt)
    return result.first() is not None


class ProjectionStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._events = PostgresEventStore(session)

    async def refresh_case(self, case_id: str) -> bool:
        history = await self._events.load_stream(case_id)
        if not history:
            return False
        projection = build_case_projection(history)
        if not await _guarded_upsert(self._session, CaseStatusProjectionModel, projection.status):
            return False
        await _guarded_upsert(self._session, TribunalProjectionModel, projection.tribunal)
        await self._session.execute(
            delete(CalendarProjectionModel).where(CalendarProjectionModel.case_id == case_id)
        )
        if projection.calendar:
            await self._session.execute(insert(CalendarProjectionModel), projection.calendar)
        return True

    async def rebuild_all(self) -> dict[str, int]:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": REBUILD_LOCK_KEY}
        )
        for model in (CalendarProjectionModel, TribunalProjectionModel, CaseStatusProjectionModel):
            await self._session.execute(delete(model))
        ids = await self._events.aggregate_ids()
        for case_id in ids:
            await self.refresh_case(case_id)
        entries = await self._session.execute(
            select(func.count()).select_from(CalendarProjectionModel)
        )
        return {"cases": len(ids), "calendar_entries": int(entries.scalar_one())}
