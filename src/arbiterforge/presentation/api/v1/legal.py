from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from arbiterforge.application import legal
from arbiterforge.core.security import Permissions
from arbiterforge.domain.regime import RegimeInput
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.presentation.deps import require_permission
from arbiterforge.presentation.schemas import (
    ArbitrabilityRequest,
    RegimeRequest,
    TermRequest,
    TribunalCheckRequest,
)

router = APIRouter(prefix="/api/v1/legal", tags=["legal"])
Reader = Annotated[UserModel, Depends(require_permission(Permissions.CASE_READ))]


@router.get("/norms")
async def list_norms(user: Reader) -> list[dict[str, Any]]:
    return legal.all_norms()


@router.get("/working-days/{year}")
async def working_days(year: int, user: Reader) -> dict[str, Any]:
    return legal.working_days(year)


@router.post("/deadlines/compute")
async def compute(body: TermRequest, user: Reader) -> dict[str, Any]:
    return legal.compute_term(body.start, body.amount, body.unit, body.rule)


@router.post("/regime")
async def regime(body: RegimeRequest, user: Reader) -> dict[str, Any]:
    return legal.regime(
        RegimeInput(
            seat_country=body.seat_country,
            party_countries=tuple(body.party_countries),
            performance_abroad=body.performance_abroad,
            closest_connection_abroad=body.closest_connection_abroad,
            foreign_investment=body.foreign_investment,
        )
    )


@router.post("/arbitrability")
async def arbitrability(body: ArbitrabilityRequest, user: Reader) -> dict[str, Any]:
    return legal.arbitrability(
        body.category,
        body.institution,
        seat_country=body.seat_country,
        all_participants_signed=body.all_participants_signed,
        sanctions_involved=body.sanctions_involved,
    )


@router.post("/tribunal-check")
async def tribunal_check(body: TribunalCheckRequest, user: Reader) -> dict[str, Any]:
    return legal.tribunal(
        body.composition,
        [m.model_dump() for m in body.members],
        institution=body.institution,
        regime_value=body.regime,
        claim_amount=body.claim_amount,
        claim_currency=body.claim_currency,
        chair_requirement_waived=body.chair_requirement_waived,
    )
