from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from arbiterforge.application.commands import CaseCommandService
from arbiterforge.core.security import Permissions
from arbiterforge.domain.exceptions import NotFoundError
from arbiterforge.infrastructure.celery_app.tasks import draft_po_summary
from arbiterforge.infrastructure.db.models import ProceduralOrderModel, UserModel
from arbiterforge.infrastructure.ollama.assistant import draft_procedural_order_summary
from arbiterforge.presentation.deps import AppSettings, DbSession, require_permission

router = APIRouter(prefix="/api/v1/procedural-orders", tags=["procedural-orders"])


def _view(po: ProceduralOrderModel) -> dict[str, Any]:
    return {
        "po_id": po.id,
        "case_id": po.case_id,
        "number": po.number,
        "ai_summary_draft": po.ai_summary_draft,
        "requires_human_review": po.requires_human_review,
        "human_accepted": po.human_accepted,
        "accepted_by": po.accepted_by,
        "accepted_at": po.accepted_at.isoformat() if po.accepted_at else None,
    }


@router.post("/{po_id}/summarize-suggest")
async def summarize_suggest(
    po_id: str,
    session: DbSession,
    user: Annotated[UserModel, Depends(require_permission(Permissions.AI_SUGGEST))],
    sync: bool = True,
) -> dict[str, Any]:
    po = await session.get(ProceduralOrderModel, po_id)
    if po is None or po.organization_id != user.org_id:
        raise NotFoundError("ProceduralOrder", po_id)
    if not sync:
        task = draft_po_summary.apply_async(args=[po_id], retry=False)
        return {"task_id": task.id, "requires_human_review": True}
    po.ai_summary_draft = await draft_procedural_order_summary(po.gist)
    po.requires_human_review = True
    po.human_accepted = False
    po.accepted_by = None
    po.accepted_at = None
    return _view(po)


@router.post("/{po_id}/accept")
async def accept_summary(
    po_id: str,
    session: DbSession,
    settings: AppSettings,
    user: Annotated[UserModel, Depends(require_permission(Permissions.PO_ACCEPT))],
) -> dict[str, Any]:
    service = CaseCommandService(session, settings.audit_hmac_secret.get_secret_value().encode())
    po = await service.accept_po_summary(po_id, actor_id=user.id, organization_id=user.org_id)
    return _view(po)
