from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.domain.audit import GENESIS_HASH, AuditRecord, ChainVerdict, seal, verify_chain
from arbiterforge.infrastructure.db.models import AuditEventModel

AUDIT_LOCK_NAMESPACE = 23


class AuditStore:
    def __init__(self, session: AsyncSession, secret: bytes) -> None:
        self._session = session
        self._secret = secret

    async def append(
        self,
        *,
        organization_id: str,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> AuditRecord:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, hashtext(:org))"),
            {"ns": AUDIT_LOCK_NAMESPACE, "org": organization_id},
        )
        last = (
            await self._session.execute(
                select(AuditEventModel.seq, AuditEventModel.event_hash)
                .where(AuditEventModel.organization_id == organization_id)
                .order_by(AuditEventModel.seq.desc())
                .limit(1)
            )
        ).first()
        record = AuditRecord(
            seq=(last.seq if last else 0) + 1,
            organization_id=organization_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            prev_hash=last.event_hash if last else GENESIS_HASH,
        )
        sealed = AuditRecord(**{**_as_kwargs(record), "event_hash": seal(record, self._secret)})
        self._session.add(
            AuditEventModel(
                organization_id=organization_id,
                seq=sealed.seq,
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                prev_hash=sealed.prev_hash,
                event_hash=sealed.event_hash,
            )
        )
        await self._session.flush()
        return sealed

    async def verify(self, organization_id: str) -> ChainVerdict:
        rows = await self._session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.organization_id == organization_id)
            .order_by(AuditEventModel.seq)
        )
        return verify_chain((_record(r) for r in rows.scalars()), self._secret)

    async def count(self, organization_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.organization_id == organization_id)
        )
        return int(result.scalar_one())


def _as_kwargs(record: AuditRecord) -> dict[str, Any]:
    return {f: getattr(record, f) for f in AuditRecord.__slots__}


def _record(row: AuditEventModel) -> AuditRecord:
    return AuditRecord(
        seq=row.seq,
        organization_id=row.organization_id,
        actor_id=row.actor_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        payload=row.payload,
        prev_hash=row.prev_hash,
        event_hash=row.event_hash,
    )
