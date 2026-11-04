from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from arbiterforge.core.security import Permissions
from arbiterforge.infrastructure.audit_store import AuditStore
from arbiterforge.infrastructure.celery_app.tasks import rebuild_projections
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.infrastructure.projections.store import ProjectionStore
from arbiterforge.infrastructure.relay.redis_stream import relay_lag
from arbiterforge.presentation.deps import AppSettings, DbSession, require_permission

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/projections/rebuild")
async def rebuild(
    session: DbSession,
    user: Annotated[UserModel, Depends(require_permission(Permissions.PROJECTION_REBUILD))],
    async_mode: bool = False,
) -> dict[str, Any]:
    if async_mode:
        task = rebuild_projections.apply_async(retry=False)
        return {"task_id": task.id, "status": "queued"}
    return {"status": "ok", **await ProjectionStore(session).rebuild_all()}


@router.get("/outbox/lag")
async def outbox_lag(
    session: DbSession,
    user: Annotated[UserModel, Depends(require_permission(Permissions.ADMIN))],
) -> dict[str, Any]:
    return await relay_lag(session)


@router.get("/audit/verify")
async def verify_audit(
    session: DbSession,
    settings: AppSettings,
    user: Annotated[UserModel, Depends(require_permission(Permissions.AUDIT_READ))],
) -> dict[str, Any]:
    store = AuditStore(session, settings.audit_hmac_secret.get_secret_value().encode())
    verdict = await store.verify(user.org_id)
    return {"organization_id": user.org_id, **verdict.to_dict()}
