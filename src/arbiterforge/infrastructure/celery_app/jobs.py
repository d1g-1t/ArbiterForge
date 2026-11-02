from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.core.config import Settings, get_settings
from arbiterforge.core.logging import get_logger
from arbiterforge.infrastructure.db.models import CalendarProjectionModel, ProceduralOrderModel
from arbiterforge.infrastructure.db.session import make_engine, make_sessionmaker
from arbiterforge.infrastructure.ollama.assistant import request_summary
from arbiterforge.infrastructure.projections.store import ProjectionStore
from arbiterforge.infrastructure.relay.redis_stream import relay_once

logger = get_logger(__name__)


async def with_session[T](
    job: Callable[[AsyncSession], Awaitable[T]], settings: Settings | None = None
) -> T:
    cfg = settings or get_settings()
    engine = make_engine(cfg.database_url, null_pool=True)
    try:
        async with make_sessionmaker(engine)() as session:
            result = await job(session)
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def relay_job(session: AsyncSession, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    redis = Redis.from_url(cfg.redis_url)
    try:
        result = await relay_once(
            session,
            redis,
            stream=cfg.event_stream,
            batch_size=cfg.relay_batch_size,
            maxlen=cfg.event_stream_maxlen,
        )
    finally:
        await redis.aclose()
    if result.published or result.duplicates:
        logger.info("relay.batch", **result.to_dict())
    return result.to_dict()


async def rebuild_job(session: AsyncSession) -> dict[str, int]:
    return await ProjectionStore(session).rebuild_all()


async def scan_deadlines_job(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(CalendarProjectionModel).where(
            CalendarProjectionModel.completed_at.is_(None),
            CalendarProjectionModel.due_at.is_not(None),
            CalendarProjectionModel.due_at < now,
        )
    )
    overdue = list(result.scalars())
    for row in overdue:
        logger.info(
            "reminder.overdue",
            case_id=row.case_id,
            entry_key=row.entry_key,
            kind=row.kind,
            due_at=row.due_at.isoformat() if row.due_at else None,
        )
    return {"overdue": len(overdue)}


async def draft_po_job(session: AsyncSession, po_id: str) -> dict[str, Any]:
    po = await session.get(ProceduralOrderModel, po_id)
    if po is None:
        return {"po_id": po_id, "status": "not_found"}
    po.ai_summary_draft = await request_summary(po.gist)
    po.requires_human_review = True
    po.human_accepted = False
    return {"po_id": po_id, "status": "drafted", "requires_human_review": True}
