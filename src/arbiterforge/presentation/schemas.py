from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from arbiterforge.domain.arbitrability import DisputeCategory
from arbiterforge.domain.terms import ComputationRule, TermUnit
from arbiterforge.domain.value_objects import (
    AwardKind,
    CorrectionKind,
    HearingFormat,
    Institution,
    NominationSide,
    PartyRole,
    PartyType,
    Regime,
    SetAsideOutcome,
    TribunalComposition,
)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OpenCaseRequest(BaseModel):
    title: str = "Arbitration case"
    institution: Institution = Institution.ICAC_MKAS
    seat_city: str = "Moscow"
    seat_country: str = Field("RU", min_length=2, max_length=2)
    language: str = "ru"
    claim_amount: Decimal | None = Field(None, ge=0)
    claim_currency: str = Field("RUB", pattern=r"^[A-Z]{3}$")
    rules_edition: str | None = None
    parties_draft: list[dict[str, Any]] = Field(default_factory=list)
    dispute_category: DisputeCategory = DisputeCategory.COMMERCIAL
    party_countries: list[str] = Field(default_factory=list)
    performance_abroad: bool = False
    closest_connection_abroad: bool = False
    foreign_investment: bool = False
    agreed_composition: TribunalComposition = TribunalComposition.THREE
    final_award_agreed: bool = False
    court_review_excluded: bool = False
    all_participants_signed: bool = False
    sanctions_involved: bool = False


class AddPartyRequest(BaseModel):
    role: PartyRole
    name: str = Field(min_length=1)
    party_type: PartyType = PartyType.LEGAL_ENTITY
    country: str = Field("RU", min_length=2, max_length=2)
    inn: str | None = None
    ogrn: str | None = None
    counsel: str | None = None


class NominateArbitratorRequest(BaseModel):
    side: NominationSide
    arbitrator_name: str = Field(min_length=1)
    law_degree: bool = False
    cv_ref: str | None = None


class MemberDTO(BaseModel):
    arbitrator_id: str
    name: str
    law_degree: bool = False
    is_chair: bool = False


class ConstituteTribunalRequest(BaseModel):
    composition: TribunalComposition = TribunalComposition.THREE
    chair_id: str | None = None
    members: list[MemberDTO] = Field(default_factory=list)
    chair_requirement_waived: bool = False
    constituted_at: date | None = None


class MilestoneDTO(BaseModel):
    code: str
    due_at: str
    label: str | None = None


class AdoptTimetableRequest(BaseModel):
    milestones: list[MilestoneDTO] = Field(min_length=1)
    po_ref: str | None = None


class ExtendMilestoneRequest(BaseModel):
    milestone_code: str
    new_due_at: str
    reason: str | None = None


class OpenRoundRequest(BaseModel):
    round_code: str
    due_at: str | None = None
    label: str | None = None


class FileSubmissionRequest(BaseModel):
    title: str
    round_code: str | None = None
    object_key: str | None = None
    pages: int | None = Field(None, ge=0)


class IssuePORequest(BaseModel):
    number: str
    gist: str = ""
    request_ai_draft: bool = False


class ScheduleHearingRequest(BaseModel):
    when: str
    where: str | None = None
    format: HearingFormat = HearingFormat.REMOTE


class AwardRequest(BaseModel):
    kind: AwardKind = AwardKind.FINAL
    operative_summary: str = ""


class ChallengeRequest(BaseModel):
    arbitrator_id: str
    party_id: str
    grounds: str = ""
    filed_on: date | None = None


class ChallengeDecisionRequest(BaseModel):
    challenge_id: str
    upheld: bool
    notified_on: date | None = None


class ReplaceArbitratorRequest(BaseModel):
    arbitrator_id: str
    replacement_name: str
    law_degree: bool = False
    reason: str | None = None


class JurisdictionRequest(BaseModel):
    has_jurisdiction: bool = True
    preliminary: bool = True
    notified_on: date | None = None
    reasoning: str = ""


class AwardReceiptRequest(BaseModel):
    party_id: str
    received_on: date | None = None


class CorrectionRequest(BaseModel):
    party_id: str
    kind: CorrectionKind = CorrectionKind.CORRECTION
    requested_on: date | None = None
    details: str = ""


class CorrectionDecisionRequest(BaseModel):
    request_id: str
    granted: bool = True
    decided_on: date | None = None


class SetAsideRequest(BaseModel):
    party_id: str
    court: str | None = None
    filed_on: date | None = None


class SetAsideResolutionRequest(BaseModel):
    outcome: SetAsideOutcome
    resolved_on: date | None = None
    court_ref: str | None = None


class CommandResult(BaseModel):
    case_id: str
    version: int
    events: list[dict[str, Any]]
    current_status: str | None = None


class TermRequest(BaseModel):
    start: date
    amount: int = Field(gt=0, le=3650)
    unit: TermUnit = TermUnit.DAYS
    rule: ComputationRule = ComputationRule.APK


class RegimeRequest(BaseModel):
    seat_country: str = Field("RU", min_length=2, max_length=2)
    party_countries: list[str] = Field(default_factory=list)
    performance_abroad: bool = False
    closest_connection_abroad: bool = False
    foreign_investment: bool = False


class ArbitrabilityRequest(BaseModel):
    category: DisputeCategory
    institution: Institution = Institution.ICAC_MKAS
    seat_country: str = Field("RU", min_length=2, max_length=2)
    all_participants_signed: bool = False
    sanctions_involved: bool = False


class TribunalCheckRequest(BaseModel):
    composition: TribunalComposition
    members: list[MemberDTO]
    institution: Institution = Institution.ICAC_MKAS
    regime: Regime = Regime.DOMESTIC
    claim_amount: Decimal | None = None
    claim_currency: str = "RUB"
    chair_requirement_waived: bool = False
