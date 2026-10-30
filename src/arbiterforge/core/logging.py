from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(email|contact_email)\s*[=:]\s*[\w.+-]+@[\w-]+\.[a-z]+"),
    re.compile(r"(?i)(password|hashed_password|token)\s*[=:]\s*\S+"),
    re.compile(r"(?i)\binn\s*[=:]\s*\d{10,12}"),
]
_MASK = "***REDACTED***"


def _mask_pii(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    if "event" in event_dict and isinstance(event_dict["event"], str):
        event = event_dict["event"]
        for pattern in _PII_PATTERNS:
            event = pattern.sub(lambda m: f"{m.group().split('=')[0].split(':')[0]}={_MASK}", event)
        event_dict["event"] = event
    return event_dict


def configure_logging(
    *, enable_masking: bool = True, log_level: str = "INFO", json: bool = True
) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if enable_masking:
        shared.insert(0, _mask_pii)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)
    for noisy in ("uvicorn.access", "httpcore", "httpx", "celery"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
