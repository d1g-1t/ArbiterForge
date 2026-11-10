from __future__ import annotations

import asyncio
import json

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arbiterforge.application.commands import CaseCommandService
from arbiterforge.core.config import Settings
from arbiterforge.domain.aggregate import ArbitrationCaseAggregate, Command
from arbiterforge.domain.exceptions import ConcurrencyError, NotFoundError
from arbiterforge.infrastructure.audit_store import AuditStore
from arbiterforge.infrastructure.db.models import (
    AuditEventModel,
    CalendarProjectionModel,
    CaseStatusProjectionModel,
    TribunalProjectionModel,
)
from arbiterforge.infrastructure.event_store.postgres import PostgresEventStore
from arbiterforge.infrastructure.projections.store import ProjectionStore
from arbiterforge.infrastructure.relay.redis_stream import relay_lag, relay_once

SECRET = b"integration-secret"
ORG = "org-int"

Maker = async_sessionmaker[AsyncSession]


async def open_case(maker: Maker, /, **payload: object) -> str:
    async with maker() as session:
        result = await CaseCommandService(session, SECRET).execute(
            case_id=None,
            command_name="open_case",
            payload=dict(payload),
            actor_id="u",
            organization_id=ORG,
            expected_version=0,
        )
        await session.commit()
    return result["case_id"]


async def command(maker: Maker, case_id: str, command_name: str, /, **payload: object) -> dict:
    async with maker() as session:
        result = await CaseCommandService(session, SECRET).execute(
            case_id=case_id,
            command_name=command_name,
            payload=dict(payload),
            actor_id="u",
            organization_id=ORG,
            expected_version=None,
        )
        await session.commit()
    return result


async def drive_to_award(maker: Maker) -> str:
    case_id = await open_case(maker, party_countries=["RU", "KZ"])
    steps = [
        ("file_case", {}),
        ("register_rfa", {"received_on": "2026-02-02"}),
        ("add_party", {"role": "respondent", "name": "R", "party_id": "r1", "country": "KZ"}),
        (
            "nominate_arbitrator",
            {"side": "institution", "arbitrator_name": "S", "arbitrator_id": "s"},
        ),
        ("constitute_tribunal", {"composition": "sole", "constituted_at": "2026-03-02"}),
        ("adopt_timetable", {"milestones": [{"code": "SoC", "due_at": "2026-04-01"}]}),
        ("open_submission_round", {"round_code": "R1", "due_at": "2026-05-01"}),
        ("file_submission", {"round_code": "R1", "title": "T"}),
        ("issue_procedural_order", {"number": "1", "gist": "g"}),
        ("start_deliberation", {}),
        ("issue_award", {}),
        ("receive_award", {"party_id": "r1", "received_on": "2026-09-30"}),
    ]
    for name, payload in steps:
        await command(maker, case_id, name, **payload)
    return case_id


async def test_parallel_writers_one_wins(sessionmaker: Maker) -> None:
    case_id = await open_case(sessionmaker)

    async def writer(ref: str) -> str:
        async with sessionmaker() as session:
            service = CaseCommandService(session, SECRET)
            try:
                await service.execute(
                    case_id=case_id,
                    command_name="file_case",
                    payload={"filing_ref": ref},
                    actor_id="u",
                    organization_id=ORG,
                    expected_version=1,
                )
                await asyncio.sleep(0.05)
                await session.commit()
            except ConcurrencyError:
                await session.rollback()
                return "conflict"
        return "ok"

    outcomes = sorted(await asyncio.gather(*(writer(f"R{n}") for n in range(4))))
    assert outcomes == ["conflict", "conflict", "conflict", "ok"]
    async with sessionmaker() as session:
        events = await PostgresEventStore(session).load_stream(case_id)
    assert [e.version for e in events] == [1, 2]


async def test_store_rejects_inconsistent_batch(sessionmaker: Maker) -> None:
    agg = ArbitrationCaseAggregate()
    events = agg.decide(Command("open_case", {}, organization_id=ORG))
    async with sessionmaker() as session:
        store = PostgresEventStore(session)
        with pytest.raises(ConcurrencyError):
            await store.append(events, expected_version=5)
        await store.append([], expected_version=0)
        await store.append(events, expected_version=0)
        with pytest.raises(ConcurrencyError) as exc:
            await store.append(events, expected_version=0)
        assert exc.value.actual == 1
        await session.rollback()


async def test_cross_tenant_command_is_not_found(sessionmaker: Maker) -> None:
    case_id = await open_case(sessionmaker)
    async with sessionmaker() as session:
        with pytest.raises(NotFoundError):
            await CaseCommandService(session, SECRET).execute(
                case_id=case_id,
                command_name="file_case",
                payload={},
                actor_id="intruder",
                organization_id="other-org",
                expected_version=None,
            )
        with pytest.raises(NotFoundError):
            await CaseCommandService(session, SECRET).load("missing", ORG)


async def snapshot(session: AsyncSession) -> tuple:
    status = (await session.execute(select(CaseStatusProjectionModel))).scalars().all()
    tribunal = (await session.execute(select(TribunalProjectionModel))).scalars().all()
    calendar = (await session.execute(select(CalendarProjectionModel))).scalars().all()
    return (
        sorted((s.case_id, s.current_status, s.version, s.regime, str(s.extra)) for s in status),
        sorted((t.case_id, t.composition, t.constituted, t.version) for t in tribunal),
        sorted((c.case_id, c.entry_key, c.kind, c.due_at, c.completed_at) for c in calendar),
    )


async def test_incremental_projection_equals_full_rebuild(sessionmaker: Maker) -> None:
    case_id = await drive_to_award(sessionmaker)
    await open_case(sessionmaker, institution="AD_HOC")
    async with sessionmaker() as session:
        before = await snapshot(session)
        row = await session.get(CaseStatusProjectionModel, case_id)
        assert row is not None
        assert row.current_status == "AwardIssued"
        stats = await ProjectionStore(session).rebuild_all()
        await session.commit()
        after = await snapshot(session)
    assert stats["cases"] == 2
    assert before == after
    keys = {c[1] for c in after[2] if c[0] == case_id}
    assert {"milestone:SoC", "round:R1", "deadline:set_aside:r1"} <= keys


async def test_stale_projection_write_is_ignored(sessionmaker: Maker) -> None:
    case_id = await drive_to_award(sessionmaker)
    async with sessionmaker() as session:
        await session.execute(
            update(CaseStatusProjectionModel)
            .where(CaseStatusProjectionModel.case_id == case_id)
            .values(version=999, current_status="Sentinel")
        )
        assert await ProjectionStore(session).refresh_case(case_id) is False
        assert await ProjectionStore(session).refresh_case("missing") is False
        row = await session.get(CaseStatusProjectionModel, case_id)
        assert row is not None
        assert row.current_status == "Sentinel"
        await session.rollback()


async def test_audit_chain_detects_tampering(sessionmaker: Maker) -> None:
    await drive_to_award(sessionmaker)
    async with sessionmaker() as session:
        store = AuditStore(session, SECRET)
        verdict = await store.verify(ORG)
        assert verdict.valid
        assert verdict.checked == await store.count(ORG) == 3
        await session.execute(
            update(AuditEventModel)
            .where(AuditEventModel.organization_id == ORG, AuditEventModel.seq == 2)
            .values(payload={"forged": True})
        )
        broken = await store.verify(ORG)
        assert (broken.valid, broken.broken_at_seq, broken.reason) == (False, 2, "hash_mismatch")
        await session.rollback()


async def test_concurrent_audit_appends_keep_chain_linear(sessionmaker: Maker) -> None:
    async def append(n: int) -> None:
        async with sessionmaker() as session:
            await AuditStore(session, SECRET).append(
                organization_id=ORG,
                actor_id="u",
                action="A",
                entity_type="T",
                entity_id=str(n),
                payload={"n": n},
            )
            await session.commit()

    await asyncio.gather(*(append(n) for n in range(8)))
    async with sessionmaker() as session:
        verdict = await AuditStore(session, SECRET).verify(ORG)
    assert verdict.valid
    assert verdict.checked == 8


async def test_relay_publishes_once_in_commit_order(
    sessionmaker: Maker, redis: Redis, settings: Settings
) -> None:
    await drive_to_award(sessionmaker)
    async with sessionmaker() as session:
        lag = await relay_lag(session)
    assert lag["pending_events"] == 13
    async with sessionmaker() as session:
        first = await relay_once(
            session, redis, stream=settings.event_stream, batch_size=5, maxlen=1000
        )
        rest = await relay_once(session, redis, stream=settings.event_stream)
        idle = await relay_once(session, redis, stream=settings.event_stream)
    assert (first.published, rest.published, idle.published) == (5, 8, 0)
    entries = await redis.xrange(settings.event_stream)
    assert len(entries) == 13
    versions = [int(fields[b"version"]) for _, fields in entries]
    assert versions == list(range(1, 14))
    async with sessionmaker() as session:
        await session.execute(
            text("UPDATE projection_checkpoints SET last_tx_id = '0'::xid8, last_global_seq = 0")
        )
        await session.commit()
        replay = await relay_once(session, redis, stream=settings.event_stream)
        lag = await relay_lag(session)
    assert (replay.published, replay.duplicates) == (0, 13)
    assert await redis.xlen(settings.event_stream) == 13
    assert lag["pending_events"] == 0


async def test_relay_waits_for_in_flight_transactions(
    sessionmaker: Maker, redis: Redis, settings: Settings
) -> None:
    slow = sessionmaker()
    agg = ArbitrationCaseAggregate()
    early = agg.decide(Command("open_case", {"title": "slow"}, organization_id=ORG))
    await PostgresEventStore(slow).append(early, expected_version=0)
    await open_case(sessionmaker, title="fast")
    async with sessionmaker() as session:
        blocked = await relay_once(session, redis, stream=settings.event_stream)
    assert blocked.published == 0
    await slow.commit()
    await slow.close()
    async with sessionmaker() as session:
        released = await relay_once(session, redis, stream=settings.event_stream)
    assert released.published == 2
    titles = [
        json.loads(f[b"payload"])["title"] for _, f in await redis.xrange(settings.event_stream)
    ]
    assert titles == ["slow", "fast"]


async def test_relay_skips_when_checkpoint_locked(
    sessionmaker: Maker, redis: Redis, settings: Settings
) -> None:
    await open_case(sessionmaker)
    async with sessionmaker() as holder, sessionmaker() as contender:
        await relay_once(holder, redis, stream=settings.event_stream)
        await holder.execute(
            text(
                "SELECT 1 FROM projection_checkpoints WHERE name = 'redis_stream_relay' FOR UPDATE"
            )
        )
        skipped = await relay_once(contender, redis, stream=settings.event_stream)
        await holder.rollback()
    assert skipped.claimed is False
