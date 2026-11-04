from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from arbiterforge.application.commands import CaseCommandService
from arbiterforge.application.queries import CaseQueryService
from arbiterforge.core.logging import get_logger
from arbiterforge.core.security import Permissions
from arbiterforge.infrastructure.celery_app.tasks import draft_po_summary
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.presentation.deps import (
    AppSettings,
    DbSession,
    IfMatch,
    parse_if_match,
    require_permission,
)
from arbiterforge.presentation.schemas import (
    AddPartyRequest,
    AdoptTimetableRequest,
    AwardReceiptRequest,
    AwardRequest,
    ChallengeDecisionRequest,
    ChallengeRequest,
    CommandResult,
    ConstituteTribunalRequest,
    CorrectionDecisionRequest,
    CorrectionRequest,
    ExtendMilestoneRequest,
    FileSubmissionRequest,
    IssuePORequest,
    JurisdictionRequest,
    NominateArbitratorRequest,
    OpenCaseRequest,
    OpenRoundRequest,
    ReplaceArbitratorRequest,
    ScheduleHearingRequest,
    SetAsideRequest,
    SetAsideResolutionRequest,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

Reader = Annotated[UserModel, Depends(require_permission(Permissions.CASE_READ))]
Writer = Annotated[UserModel, Depends(require_permission(Permissions.CASE_WRITE))]
TribunalManager = Annotated[UserModel, Depends(require_permission(Permissions.TRIBUNAL_MANAGE))]
Filer = Annotated[UserModel, Depends(require_permission(Permissions.SUBMISSION_FILE))]
AwardIssuer = Annotated[UserModel, Depends(require_permission(Permissions.AWARD_ISSUE))]


async def _run(
    session: DbSession,
    settings: AppSettings,
    user: UserModel,
    case_id: str | None,
    name: str,
    payload: dict[str, Any],
    expected: int | None,
) -> CommandResult:
    service = CaseCommandService(session, settings.audit_hmac_secret.get_secret_value().encode())
    result = await service.execute(
        case_id=case_id,
        command_name=name,
        payload=payload,
        actor_id=user.id,
        organization_id=user.org_id,
        expected_version=expected,
    )
    return CommandResult(**result)


def _dump(body: BaseModel | None) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude_none=True) if body else {}


@router.get("")
async def list_cases(session: DbSession, user: Reader) -> list[dict[str, Any]]:
    return await CaseQueryService(session).list_cases(user.org_id)


@router.post("", response_model=CommandResult, status_code=201)
async def open_case(
    body: OpenCaseRequest, session: DbSession, settings: AppSettings, user: Writer
) -> CommandResult:
    payload = _dump(body)
    payload["seat"] = {"city": payload.pop("seat_city"), "country": payload.pop("seat_country")}
    return await _run(session, settings, user, None, "open_case", payload, 0)


@router.get("/{case_id}")
async def get_case(case_id: str, session: DbSession, user: Reader) -> dict[str, Any]:
    return await CaseQueryService(session).get_case(case_id, user.org_id)


@router.get("/{case_id}/timeline")
async def get_timeline(case_id: str, session: DbSession, user: Reader) -> list[dict[str, Any]]:
    return await CaseQueryService(session).timeline(case_id, user.org_id)


@router.get("/{case_id}/tribunal")
async def get_tribunal(case_id: str, session: DbSession, user: Reader) -> dict[str, Any]:
    return await CaseQueryService(session).tribunal(case_id, user.org_id)


@router.get("/{case_id}/deadlines")
async def get_deadlines(case_id: str, session: DbSession, user: Reader) -> list[dict[str, Any]]:
    return await CaseQueryService(session).deadlines(case_id, user.org_id)


@router.post("/{case_id}/commands/file", response_model=CommandResult)
async def file_case(
    case_id: str,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
    filing_ref: str = "RFA-001",
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "file_case",
        {"filing_ref": filing_ref},
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/register-rfa", response_model=CommandResult)
async def register_rfa(
    case_id: str,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
    received_on: date | None = None,
) -> CommandResult:
    payload = {"received_on": received_on.isoformat()} if received_on else {}
    return await _run(
        session, settings, user, case_id, "register_rfa", payload, parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/add-party", response_model=CommandResult)
async def add_party(
    case_id: str,
    body: AddPartyRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "add_party", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/nominate-arbitrator", response_model=CommandResult)
async def nominate(
    case_id: str,
    body: NominateArbitratorRequest,
    session: DbSession,
    settings: AppSettings,
    user: TribunalManager,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "nominate_arbitrator",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/constitute-tribunal", response_model=CommandResult)
async def constitute(
    case_id: str,
    body: ConstituteTribunalRequest,
    session: DbSession,
    settings: AppSettings,
    user: TribunalManager,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "constitute_tribunal",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/challenge-arbitrator", response_model=CommandResult)
async def challenge(
    case_id: str,
    body: ChallengeRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "challenge_arbitrator",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/decide-challenge", response_model=CommandResult)
async def decide_challenge(
    case_id: str,
    body: ChallengeDecisionRequest,
    session: DbSession,
    settings: AppSettings,
    user: TribunalManager,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "decide_arbitrator_challenge",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/replace-arbitrator", response_model=CommandResult)
async def replace_arbitrator(
    case_id: str,
    body: ReplaceArbitratorRequest,
    session: DbSession,
    settings: AppSettings,
    user: TribunalManager,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "replace_arbitrator",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/rule-on-jurisdiction", response_model=CommandResult)
async def rule_on_jurisdiction(
    case_id: str,
    body: JurisdictionRequest,
    session: DbSession,
    settings: AppSettings,
    user: TribunalManager,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "rule_on_jurisdiction",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/adopt-timetable", response_model=CommandResult)
async def adopt_timetable(
    case_id: str,
    body: AdoptTimetableRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "adopt_timetable", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/extend-milestone", response_model=CommandResult)
async def extend_milestone(
    case_id: str,
    body: ExtendMilestoneRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "extend_milestone", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/open-submission-round", response_model=CommandResult)
async def open_round(
    case_id: str,
    body: OpenRoundRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "open_submission_round",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/file-submission", response_model=CommandResult)
async def file_submission(
    case_id: str,
    body: FileSubmissionRequest,
    session: DbSession,
    settings: AppSettings,
    user: Filer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "file_submission", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/issue-procedural-order", response_model=CommandResult)
async def issue_po(
    case_id: str,
    body: IssuePORequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    payload = {
        "number": body.number,
        "gist": body.gist,
        "requires_human_review": body.request_ai_draft,
    }
    result = await _run(
        session,
        settings,
        user,
        case_id,
        "issue_procedural_order",
        payload,
        parse_if_match(if_match),
    )
    if body.request_ai_draft:
        await session.commit()
        po_id = result.events[0]["payload"]["po_id"]
        try:
            draft_po_summary.apply_async(args=[po_id], retry=False)
        except Exception as exc:
            logger.warning("po.draft_enqueue_failed", po_id=po_id, error=type(exc).__name__)
    return result


@router.post("/{case_id}/commands/schedule-hearing", response_model=CommandResult)
async def schedule_hearing(
    case_id: str,
    body: ScheduleHearingRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "schedule_hearing", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/mark-hearing-held", response_model=CommandResult)
async def hearing_held(
    case_id: str,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
    hearing_id: str | None = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "mark_hearing_held",
        {"hearing_id": hearing_id},
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/start-deliberation", response_model=CommandResult)
async def start_deliberation(
    case_id: str, session: DbSession, settings: AppSettings, user: Writer, if_match: IfMatch = None
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "start_deliberation", {}, parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/draft-award", response_model=CommandResult)
async def draft_award(
    case_id: str,
    body: AwardRequest,
    session: DbSession,
    settings: AppSettings,
    user: AwardIssuer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "draft_award", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/issue-award", response_model=CommandResult)
async def issue_award(
    case_id: str,
    body: AwardRequest,
    session: DbSession,
    settings: AppSettings,
    user: AwardIssuer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "issue_award", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/receive-award", response_model=CommandResult)
async def receive_award(
    case_id: str,
    body: AwardReceiptRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "receive_award", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/request-correction", response_model=CommandResult)
async def request_correction(
    case_id: str,
    body: CorrectionRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "request_correction",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/decide-correction", response_model=CommandResult)
async def decide_correction(
    case_id: str,
    body: CorrectionDecisionRequest,
    session: DbSession,
    settings: AppSettings,
    user: AwardIssuer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "decide_correction",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/file-set-aside", response_model=CommandResult)
async def file_set_aside(
    case_id: str,
    body: SetAsideRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session, settings, user, case_id, "file_set_aside", _dump(body), parse_if_match(if_match)
    )


@router.post("/{case_id}/commands/resolve-set-aside", response_model=CommandResult)
async def resolve_set_aside(
    case_id: str,
    body: SetAsideResolutionRequest,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "resolve_set_aside",
        _dump(body),
        parse_if_match(if_match),
    )


@router.post("/{case_id}/commands/close", response_model=CommandResult)
async def close_case(
    case_id: str, session: DbSession, settings: AppSettings, user: Writer, if_match: IfMatch = None
) -> CommandResult:
    return await _run(session, settings, user, case_id, "close_case", {}, parse_if_match(if_match))


@router.post("/{case_id}/commands/terminate", response_model=CommandResult)
async def terminate_case(
    case_id: str,
    session: DbSession,
    settings: AppSettings,
    user: Writer,
    if_match: IfMatch = None,
    reason: str = "terminated",
) -> CommandResult:
    return await _run(
        session,
        settings,
        user,
        case_id,
        "terminate_case",
        {"reason": reason},
        parse_if_match(if_match),
    )
