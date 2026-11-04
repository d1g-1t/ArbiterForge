from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from arbiterforge.domain.exceptions import (
    AuthorizationError,
    CalendarCoverageError,
    ConcurrencyError,
    DomainError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)
from arbiterforge.domain.legal_basis import norms


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConcurrencyError)
    async def concurrency(_: Request, exc: ConcurrencyError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "aggregate_id": exc.aggregate_id,
                "expected_version": exc.expected,
                "actual_version": exc.actual,
            },
        )

    @app.exception_handler(InvalidTransitionError)
    async def transition(_: Request, exc: InvalidTransitionError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AuthorizationError)
    async def forbidden(_: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "basis": list(exc.basis), "norms": norms(*exc.basis)},
        )

    @app.exception_handler(CalendarCoverageError)
    async def calendar(_: Request, exc: CalendarCoverageError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc), "year": exc.year})

    @app.exception_handler(DomainError)
    async def domain(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
