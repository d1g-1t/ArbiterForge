from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arbiterforge.core.config import Settings, get_settings
from arbiterforge.infrastructure.celery_app import jobs, tasks
from arbiterforge.infrastructure.db.models import ProceduralOrderModel, UserModel
from arbiterforge.seed import DEMO_EMAIL, seed_demo
from tests.integration.test_persistence import command, drive_to_award, open_case

Maker = async_sessionmaker[AsyncSession]


async def test_seed_is_fictional_and_idempotent(sessionmaker: Maker, settings: Settings) -> None:
    async with sessionmaker() as session:
        first = await seed_demo(session, settings)
        await session.commit()
    async with sessionmaker() as session:
        second = await seed_demo(session, settings)
        admin = (
            await session.execute(select(UserModel).where(UserModel.email == DEMO_EMAIL))
        ).scalar_one()
    assert first["status"] == "seeded"
    assert len(first["cases"]) == 2
    assert second == {"status": "already_seeded"}
    assert admin.role == "ADMIN"


async def test_jobs_against_real_services(
    sessionmaker: Maker, settings: Settings, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = await drive_to_award(sessionmaker)
    async with sessionmaker() as session:
        relayed = await jobs.relay_job(session, settings)
        rebuilt = await jobs.rebuild_job(session)
        overdue = await jobs.scan_deadlines_job(session)
        await session.commit()
    assert relayed["published"] == 13
    assert await redis.xlen(settings.event_stream) == 13
    assert rebuilt["cases"] == 1
    assert overdue["overdue"] >= 1

    async def fake_summary(gist: str) -> str:
        return "резюме: " + gist

    monkeypatch.setattr(jobs, "request_summary", fake_summary)
    async with sessionmaker() as session:
        po = (await session.execute(select(ProceduralOrderModel))).scalar_one()
        drafted = await jobs.draft_po_job(session, po.id)
        missing = await jobs.draft_po_job(session, "missing")
        await session.commit()
    assert drafted["status"] == "drafted"
    assert missing["status"] == "not_found"
    await command(sessionmaker, case_id, "close_case")


async def test_celery_tasks_run_with_fresh_event_loop(
    sessionmaker: Maker, settings: Settings, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    await open_case(sessionmaker)
    monkeypatch.setenv("ARBITERFORGE_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ARBITERFORGE_REDIS_URL", settings.redis_url)
    monkeypatch.setenv("ARBITERFORGE_EVENT_STREAM", settings.event_stream)
    get_settings.cache_clear()
    try:
        relayed = await asyncio.to_thread(tasks.relay_events.run)
        rebuilt = await asyncio.to_thread(tasks.rebuild_projections.run)
        scanned = await asyncio.to_thread(tasks.scan_deadlines.run)
        drafted = await asyncio.to_thread(tasks.draft_po_summary.run, "missing")
    finally:
        get_settings.cache_clear()
    assert relayed["published"] == 1
    assert rebuilt["cases"] == 1
    assert scanned == {"overdue": 0}
    assert drafted["status"] == "not_found"
    assert await redis.xlen(settings.event_stream) == 1
