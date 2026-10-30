from __future__ import annotations

from enum import StrEnum

EVENT_SCHEMA_VERSION = 2


class EventType(StrEnum):
    CASE_OPENED = "CaseOpened"
    CASE_FILED = "CaseFiled"
    REQUEST_FOR_ARBITRATION_REGISTERED = "RequestForArbitrationRegistered"
    PARTY_ADDED = "PartyAdded"
    PARTY_UPDATED = "PartyUpdated"
    ARBITRATOR_NOMINATED = "ArbitratorNominated"
    ARBITRATOR_ACCEPTED = "ArbitratorAccepted"
    ARBITRATOR_CHALLENGED = "ArbitratorChallenged"
    ARBITRATOR_CHALLENGE_DECIDED = "ArbitratorChallengeDecided"
    ARBITRATOR_REPLACED = "ArbitratorReplaced"
    TRIBUNAL_CONSTITUTED = "TribunalConstituted"
    JURISDICTION_RULED = "JurisdictionRuled"
    PROCEDURAL_TIMETABLE_ADOPTED = "ProceduralTimetableAdopted"
    MILESTONE_EXTENDED = "MilestoneExtended"
    SUBMISSION_ROUND_OPENED = "SubmissionRoundOpened"
    SUBMISSION_FILED = "SubmissionFiled"
    PROCEDURAL_ORDER_ISSUED = "ProceduralOrderIssued"
    HEARING_SCHEDULED = "HearingScheduled"
    HEARING_HELD = "HearingHeld"
    HEARING_ADJOURNED = "HearingAdjourned"
    DOCUMENTS_ONLY_CLOSED = "DocumentsOnlyClosed"
    DELIBERATION_STARTED = "DeliberationStarted"
    AWARD_DRAFTED = "AwardDrafted"
    AWARD_ISSUED = "AwardIssued"
    AWARD_RECEIVED = "AwardReceived"
    CORRECTION_REQUESTED = "CorrectionRequested"
    CORRECTION_DECIDED = "CorrectionDecided"
    SET_ASIDE_NOTED = "SetAsideNoted"
    CHALLENGE_RESOLVED = "ChallengeResolved"
    CASE_TERMINATED = "CaseTerminated"
    CASE_CLOSED = "CaseClosed"
