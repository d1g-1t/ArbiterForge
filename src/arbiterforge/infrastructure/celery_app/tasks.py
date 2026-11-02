from __future__ import annotations

import asyncio
from typing import Any

import httpx
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError

from arbiterforge.infrastructure.celery_app import jobs
from arbiterforge.infrastructure.celery_app.celery_app import celery_app

TRANSIENT = (RedisError, OperationalError, OSError)


@celery_app.task(
    name="arbiterforge.relay_events",
    autoretry_for=TRANSIENT,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def relay_events() -> dict[str, Any]:
    return asyncio.run(jobs.with_session(jobs.relay_job))


@celery_app.task(name="arbiterforge.rebuild_projections")
def rebuild_projections() -> dict[str, int]:
    return asyncio.run(jobs.with_session(jobs.rebuild_job))


@celery_app.task(name="arbiterforge.scan_deadlines")
def scan_deadlines() -> dict[str, int]:
    return asyncio.run(jobs.with_session(jobs.scan_deadlines_job))


@celery_app.task(
    name="arbiterforge.draft_po_summary",
    autoretry_for=(httpx.TransportError, httpx.HTTPStatusError),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
def draft_po_summary(po_id: str) -> dict[str, Any]:
    return asyncio.run(jobs.with_session(lambda s: jobs.draft_po_job(s, po_id)))
