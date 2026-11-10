from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from arbiterforge.core.config import Settings
from arbiterforge.core.security import Role, create_access_token, hash_password
from arbiterforge.infrastructure.db.models import OrganizationModel, UserModel
from arbiterforge.infrastructure.db.session import make_engine, make_sessionmaker
from arbiterforge.main import create_app

ROOT = Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("ARBITERFORGE_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("ARBITERFORGE_TEST_REDIS_URL")
TABLES = (
    "domain_events",
    "case_status_projection",
    "calendar_projection",
    "tribunal_projection",
    "projection_checkpoints",
    "procedural_orders",
    "audit_events",
    "users",
    "organizations",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
            if not (DB_URL and REDIS_URL):
                item.add_marker(pytest.mark.skip(reason="ARBITERFORGE_TEST_* not set"))


def run_alembic(*args: str, db_url: str | None = None) -> subprocess.CompletedProcess[str]:
    target = db_url or DB_URL
    assert target
    env = {**os.environ, "ARBITERFORGE_DATABASE_URL": target}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    assert DB_URL
    assert REDIS_URL
    return Settings(
        env="test",
        database_url=DB_URL,
        redis_url=REDIS_URL,
        event_stream=f"test:events:{uuid.uuid4().hex[:8]}",
        log_json=False,
        ollama_base_url="http://127.0.0.1:9",
        ollama_timeout_seconds=0.5,
    )


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> None:
    for args in (("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*args)
        assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
async def engine(settings: Settings, migrated: None) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(settings.database_url)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url)
    await client.delete(settings.event_stream)
    yield client
    await client.delete(settings.event_stream)
    await client.aclose()


@pytest.fixture(autouse=True)
async def clean(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


@dataclass
class Tenant:
    org_id: str
    users: dict[str, str]

    def headers(self, role: Role = Role.ADMIN) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.users[role]}"}


async def make_tenant(maker: async_sessionmaker[AsyncSession], suffix: str) -> Tenant:
    async with maker() as session:
        org = OrganizationModel(
            id=str(uuid.uuid4()),
            name=f"Тест {suffix}",
            inn=f"00009{suffix}0",
            ogrn=f"10000009{suffix}1",
        )
        session.add(org)
        await session.flush()
        tokens: dict[str, str] = {}
        password = hash_password("pw")
        for role in Role:
            user = UserModel(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=f"{role.value.lower()}.{suffix}@test.local",
                hashed_password=password,
                role=role.value,
                full_name=role.value,
            )
            session.add(user)
            tokens[role] = create_access_token(
                {"sub": user.id, "email": user.email, "role": user.role, "org_id": org.id}
            )
        await session.commit()
    return Tenant(org.id, tokens)


@pytest.fixture
async def tenant(sessionmaker: async_sessionmaker[AsyncSession]) -> Tenant:
    return await make_tenant(sessionmaker, "1111")


@pytest.fixture
async def other_tenant(sessionmaker: async_sessionmaker[AsyncSession]) -> Tenant:
    return await make_tenant(sessionmaker, "2222")


@pytest.fixture
async def client(settings: Settings, engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
