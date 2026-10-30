from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Institution(StrEnum):
    ICAC_MKAS = "ICAC_MKAS"
    MAC = "MAC"
    RAC = "RAC"
    AD_HOC = "AD_HOC"

    @property
    def is_institutional(self) -> bool:
        return self is not Institution.AD_HOC


class Regime(StrEnum):
    INTERNATIONAL = "INTERNATIONAL"
    DOMESTIC = "DOMESTIC"
    FOREIGN_SEAT = "FOREIGN_SEAT"


class CaseStatus(StrEnum):
    INTAKE = "Intake"
    FILED = "Filed"
    TRIBUNAL_PENDING = "TribunalPending"
    TRIBUNAL_CONSTITUTED = "TribunalConstituted"
    TIMETABLE_SET = "TimetableSet"
    SUBMISSIONS_OPEN = "SubmissionsOpen"
    HEARING_SCHEDULED = "HearingScheduled"
    HEARING_HELD = "HearingHeld"
    DELIBERATION = "Deliberation"
    AWARD_DRAFT = "AwardDraft"
    AWARD_ISSUED = "AwardIssued"
    SET_ASIDE_CHALLENGE = "SetAsideChallenge"
    CLOSED = "Closed"
    TERMINATED = "Terminated"


class PartyRole(StrEnum):
    CLAIMANT = "claimant"
    RESPONDENT = "respondent"
    ADDITIONAL = "additional"


class PartyType(StrEnum):
    LEGAL_ENTITY = "legal_entity"
    INDIVIDUAL_ENTREPRENEUR = "individual_entrepreneur"
    INDIVIDUAL = "individual"


class NominationSide(StrEnum):
    CLAIMANT = "claimant"
    RESPONDENT = "respondent"
    CO_ARBITRATORS = "co_arbitrators"
    INSTITUTION = "institution"
    COURT = "court"


class HearingFormat(StrEnum):
    IN_PERSON = "in_person"
    HYBRID = "hybrid"
    REMOTE = "remote"


class AwardKind(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"
    AGREED_TERMS = "agreed_terms"


class TribunalComposition(StrEnum):
    SOLE = "sole"
    THREE = "three"
    OTHER = "other"


class CorrectionKind(StrEnum):
    CORRECTION = "correction"
    INTERPRETATION = "interpretation"
    ADDITIONAL_AWARD = "additional_award"


class SetAsideOutcome(StrEnum):
    DISMISSED = "dismissed"
    ANNULLED = "annulled"
    WITHDRAWN = "withdrawn"


_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    if re.fullmatch(r"\d{10}", value):
        return _check_digit(value, _INN10_WEIGHTS) == int(value[9])
    if re.fullmatch(r"\d{12}", value):
        return _check_digit(value, _INN12_WEIGHTS_1) == int(value[10]) and _check_digit(
            value, _INN12_WEIGHTS_2
        ) == int(value[11])
    return False


def is_valid_ogrn(value: str) -> bool:
    if re.fullmatch(r"\d{13}", value):
        return int(value[:12]) % 11 % 10 == int(value[12])
    if re.fullmatch(r"\d{15}", value):
        return int(value[:14]) % 13 % 10 == int(value[14])
    return False


@dataclass(frozen=True, slots=True)
class Inn:
    value: str

    def __post_init__(self) -> None:
        if not is_valid_inn(self.value):
            raise ValueError(f"Invalid INN checksum: {self.value}")


@dataclass(frozen=True, slots=True)
class Ogrn:
    value: str

    def __post_init__(self) -> None:
        if not is_valid_ogrn(self.value):
            raise ValueError(f"Invalid OGRN checksum: {self.value}")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "RUB"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("Money amount must be non-negative")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Currency must be ISO 4217 code")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    aggregate_id: str
    aggregate_type: str
    version: int
    event_type: str
    payload: dict[str, Any]
    occurred_at: str
    actor_id: str | None
    metadata: dict[str, Any]

    @property
    def organization_id(self) -> str | None:
        return self.metadata.get("organization_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "version": self.version,
            "event_type": self.event_type,
            "payload": self.payload,
            "occurred_at": self.occurred_at,
            "actor_id": self.actor_id,
            "metadata": self.metadata,
        }
