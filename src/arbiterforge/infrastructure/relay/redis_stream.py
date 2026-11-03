from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from redis.exceptions import ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RELAY_NAME = "redis_stream_relay"

_CLAIM = text(
    "SELECT last_tx_id::text AS tx, last_global_seq AS seq FROM projection_checkpoints "
    "WHERE name = :name FOR UPDATE SKIP LOCKED"
)
_ENSURE = text(
    "INSERT INTO projection_checkpoints (name, last_global_seq, last_tx_id, updated_at) "
    "VALUES (:name, 0, '0'::xid8, now()) ON CONFLICT (name) DO NOTHING"
)
_BATCH = text(
    "SELECT global_seq, tx_id::text AS tx, event_id, aggregate_id, aggregate_type, version, "
    "event_type, payload, occurred_at, actor_id, organization_id "
    "FROM domain_events "
    "WHERE (tx_id, global_seq) > (CAST(:tx AS xid8), :seq) "
    "AND tx_id < pg_snapshot_xmin(pg_current_snapshot()) "
    "ORDER BY tx_id, global_seq LIMIT :limit"
)
_ADVANCE = text(
    "UPDATE projection_checkpoints SET last_tx_id = CAST(:tx AS xid8), last_global_seq = :seq, "
    "updated_at = now() WHERE name = :name"
)
_LAG = text(
    "SELECT count(*) AS pending, min(e.occurred_at) AS oldest "
    "FROM domain_events e, projection_checkpoints c "
    "WHERE c.name = :name AND (e.tx_id, e.global_seq) > (c.last_tx_id, c.last_global_seq)"
)
_LAG_NO_CHECKPOINT = text(
    "SELECT count(*) AS pending, min(occurred_at) AS oldest FROM domain_events"
)


class StreamClient(Protocol):
    async def xadd(self, name: str, fields: dict[str, Any], **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class RelayResult:
    claimed: bool
    published: int
    duplicates: int
    last_stream_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimed": self.claimed,
            "published": self.published,
            "duplicates": self.duplicates,
            "last_stream_id": self.last_stream_id,
        }


def stream_id(tx_id: str, global_seq: int) -> str:
    return f"{int(tx_id)}-{global_seq}"


def _fields(row: Any) -> dict[str, str]:
    return {
        "event_id": row.event_id,
        "aggregate_id": row.aggregate_id,
        "aggregate_type": row.aggregate_type,
        "version": str(row.version),
        "event_type": row.event_type,
        "organization_id": row.organization_id or "",
        "occurred_at": row.occurred_at.isoformat(),
        "payload": json.dumps(row.payload, ensure_ascii=False, sort_keys=True),
    }


async def relay_once(
    session: AsyncSession,
    redis: StreamClient,
    *,
    stream: str,
    batch_size: int = 500,
    maxlen: int | None = None,
) -> RelayResult:
    await session.execute(_ENSURE, {"name": RELAY_NAME})
    await session.commit()
    checkpoint = (await session.execute(_CLAIM, {"name": RELAY_NAME})).first()
    if checkpoint is None:
        await session.rollback()
        return RelayResult(False, 0, 0, None)
    rows = (
        await session.execute(
            _BATCH, {"tx": int(checkpoint.tx), "seq": checkpoint.seq, "limit": batch_size}
        )
    ).all()
    published = duplicates = 0
    last: str | None = None
    for row in rows:
        sid = stream_id(row.tx, row.global_seq)
        kwargs: dict[str, Any] = {"id": sid}
        if maxlen:
            kwargs.update(maxlen=maxlen, approximate=True)
        try:
            await redis.xadd(stream, _fields(row), **kwargs)
            published += 1
        except ResponseError as exc:
            if "equal or smaller" not in str(exc):
                raise
            duplicates += 1
        last = sid
        await session.execute(
            _ADVANCE, {"tx": int(row.tx), "seq": row.global_seq, "name": RELAY_NAME}
        )
    await session.commit()
    return RelayResult(True, published, duplicates, last)


async def relay_lag(session: AsyncSession) -> dict[str, Any]:
    row = (await session.execute(_LAG, {"name": RELAY_NAME})).first()
    exists = (
        await session.execute(
            text("SELECT 1 FROM projection_checkpoints WHERE name = :name"), {"name": RELAY_NAME}
        )
    ).first()
    if exists is None:
        row = (await session.execute(_LAG_NO_CHECKPOINT)).first()
    assert row is not None
    return {
        "relay": RELAY_NAME,
        "pending_events": int(row.pending),
        "oldest_pending_at": row.oldest.isoformat() if row.oldest else None,
    }
