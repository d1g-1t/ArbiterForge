from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from arbiterforge.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "arbiterforge",
    broker=settings.broker_url,
    include=["arbiterforge.infrastructure.celery_app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_routes={
        "arbiterforge.relay_events": {"queue": "relay"},
        "arbiterforge.rebuild_projections": {"queue": "projection"},
        "arbiterforge.scan_deadlines": {"queue": "reminders"},
        "arbiterforge.draft_po_summary": {"queue": "ai_draft"},
    },
    beat_schedule={
        "relay-events": {
            "task": "arbiterforge.relay_events",
            "schedule": settings.relay_interval_seconds,
        },
        "scan-deadlines-hourly": {
            "task": "arbiterforge.scan_deadlines",
            "schedule": crontab(minute=5),
        },
    },
)
