from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from arbiterforge.core.config import Settings, get_settings
from arbiterforge.core.logging import configure_logging, get_logger
from arbiterforge.infrastructure.db.session import make_engine, make_sessionmaker
from arbiterforge.presentation.api.v1 import (
    admin,
    auth,
    calendar,
    cases,
    exports,
    health,
    legal,
    orgs,
    procedural_orders,
)
from arbiterforge.presentation.errors import register_exception_handlers
from arbiterforge.presentation.middleware import RequestContextMiddleware

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(enable_masking=cfg.log_masking, json=cfg.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(cfg.database_url)
        app.state.settings = cfg
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        logger.info("app.starting", env=cfg.env, port=cfg.port)
        yield
        await engine.dispose()
        logger.info("app.stopped")

    app = FastAPI(
        title="ArbiterForge",
        description=(
            "Event-sourced case management for commercial arbitration in Russia "
            "(ICAC, MAC, ad hoc) with a statutory deadline engine."
        ),
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    for module in (health, auth, orgs, cases, calendar, admin, exports, procedural_orders, legal):
        app.include_router(module.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
