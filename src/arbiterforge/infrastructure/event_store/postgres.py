from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.domain.exceptions import ConcurrencyError
from arbiterforge.domain.value_objects import EventEnvelope
from arbiterforge.infrastructure.db.models import DomainEventModel

REBUILD_LOCK_KEY = 23_0001


def to_envelope(row: DomainEventModel) -> EventEnvelope:
    return EventEnvelope(
        event_id=row.event_id,
        aggregate_id=row.aggregate_id,
        aggregate_type=row.aggregate_type,
        version=row.version,
        event_type=row.event_type,
        payload=row.payload,
        occurred_at=row.occurred_at.isoformat(),
        actor_id=row.actor_id,
        metadata={**(row.event_metadata or {}), "global_seq": row.global_seq},
    )


def _row(ev: EventEnvelope) -> dict[str, Any]:
    return {
        "event_id": ev.event_id,
        "aggregate_id": ev.aggregate_id,
        "aggregate_type": ev.aggregate_type,
        "version": ev.version,
        "event_type": ev.event_type,
        "payload": ev.payload,
        "occurred_at": datetime.fromisoformat(ev.occurred_at),
        "actor_id": ev.actor_id,
        "organization_id": ev.organization_id,
        "event_metadata": ev.metadata,
    }


class PostgresEventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current_version(self, aggregate_id: str) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(DomainEventModel.version), 0)).where(
                DomainEventModel.aggregate_id == aggregate_id
            )
        )
        return int(result.scalar_one())

    async def append(self, events: list[EventEnvelope], *, expected_version: int) -> None:
        if not events:
            return
        aggregate_id = events[0].aggregate_id
        for offset, ev in enumerate(events, start=1):
            if ev.aggregate_id != aggregate_id or ev.version != expected_version + offset:
                raise ConcurrencyError(aggregate_id, expected_version, ev.version - offset)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": REBUILD_LOCK_KEY}
        )
        try:
            async with self._session.begin_nested():
                await self._session.execute(insert(DomainEventModel), [_row(ev) for ev in events])
        except IntegrityError as exc:
            if "uq_domain_events_agg_version" not in str(exc.orig):
                raise
            actual = await self.current_version(aggregate_id)
            raise ConcurrencyError(aggregate_id, expected_version, actual) from None

    async def load_stream(self, aggregate_id: str) -> list[EventEnvelope]:
        result = await self._session.execute(
            select(DomainEventModel)
            .where(DomainEventModel.aggregate_id == aggregate_id)
            .order_by(DomainEventModel.version)
        )
        return [to_envelope(r) for r in result.scalars()]

    async def aggregate_ids(self) -> list[str]:
        result = await self._session.execute(
            select(DomainEventModel.aggregate_id)
            .group_by(DomainEventModel.aggregate_id)
            .order_by(func.min(DomainEventModel.global_seq))
        )
        return list(result.scalars())
