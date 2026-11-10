from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.integration.conftest import DB_URL, run_alembic


@pytest.fixture
async def scratch_db() -> AsyncIterator[str]:
    assert DB_URL
    url = make_url(DB_URL)
    name = f"af_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(raw_dsn(DB_URL))
    await admin.execute(f'CREATE DATABASE "{name}"')
    yield url.set(database=name).render_as_string(hide_password=False)
    await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    await admin.close()


def alembic_on(db_url: str, *args: str) -> str:
    result = run_alembic(*args, db_url=db_url)
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


def raw_dsn(db_url: str) -> str:
    return make_url(db_url).set(drivername="postgresql").render_as_string(hide_password=False)


async def test_upgrade_downgrade_check_and_legacy_audit(scratch_db: str) -> None:
    alembic_on(scratch_db, "upgrade", "0001_initial")
    conn = await asyncpg.connect(raw_dsn(scratch_db))
    try:
        for n in range(3):
            await conn.execute(
                "INSERT INTO audit_events (id, organization_id, action, entity_type, entity_id, "
                "payload, prev_hash, event_hash, created_at) "
                "VALUES ($1, 'org', 'A', 'T', 'e', '{}', 'p', 'h', "
                "now() + make_interval(secs => $2))",
                str(uuid.uuid4()),
                n,
            )
        await conn.execute(
            "INSERT INTO domain_events (event_id, aggregate_id, aggregate_type, version, "
            "event_type, payload, occurred_at, metadata, created_at) "
            "VALUES ('e1', 'a1', 'T', 1, 'CaseOpened', '{}', now(), '{}', now())"
        )
    finally:
        await conn.close()
    alembic_on(scratch_db, "upgrade", "head")
    assert "No new upgrade operations detected" in alembic_on(scratch_db, "check")
    conn = await asyncpg.connect(raw_dsn(scratch_db))
    try:
        seqs = [r["seq"] for r in await conn.fetch("SELECT seq FROM audit_events ORDER BY seq")]
        assert seqs == [1, 2, 3]
        tx = await conn.fetchval("SELECT tx_id::text FROM domain_events")
        assert int(tx) > 0
        assert await conn.fetchval("SELECT to_regclass('outbox_events')") is None
    finally:
        await conn.close()
    alembic_on(scratch_db, "downgrade", "base")
    alembic_on(scratch_db, "upgrade", "head")
