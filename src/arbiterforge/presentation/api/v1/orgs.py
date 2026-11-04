from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from arbiterforge.infrastructure.db.models import OrganizationModel
from arbiterforge.presentation.deps import CurrentUser, DbSession

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


@router.get("/me")
async def me(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    org = await session.get(OrganizationModel, user.org_id)
    assert org is not None
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "full_name": user.full_name,
        },
        "organization": {"id": org.id, "name": org.name, "inn": org.inn, "ogrn": org.ogrn},
    }
