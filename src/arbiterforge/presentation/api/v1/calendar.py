from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from arbiterforge.application.queries import CaseQueryService
from arbiterforge.core.security import Permissions
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.presentation.deps import DbSession, require_permission

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


@router.get("")
async def get_calendar(
    session: DbSession,
    user: Annotated[UserModel, Depends(require_permission(Permissions.CASE_READ))],
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    return await CaseQueryService(session).calendar(
        user.org_id, date_from=date_from, date_to=date_to, kind=kind
    )
