from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from arbiterforge.application.queries import CaseQueryService
from arbiterforge.core.security import Permissions
from arbiterforge.domain.deadlines import compute_case_deadlines
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.infrastructure.exporters.timeline import build_timeline_html
from arbiterforge.presentation.deps import DbSession, require_permission

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


@router.get("/timeline-packs/{case_id}", response_class=HTMLResponse)
async def timeline_pack(
    case_id: str,
    session: DbSession,
    user: Annotated[UserModel, Depends(require_permission(Permissions.CASE_READ))],
) -> HTMLResponse:
    events = await CaseQueryService(session).events(case_id, user.org_id)
    deadlines = [d.to_dict() for d in compute_case_deadlines(events)]
    return HTMLResponse(build_timeline_html(case_id, events, deadlines))
