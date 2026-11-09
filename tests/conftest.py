from __future__ import annotations

from datetime import date

import pytest

from arbiterforge.domain.aggregate import ArbitrationCaseAggregate, Command

ORG = "org-test"
ACTOR = "user-test"


class CaseDriver:
    def __init__(self, **open_payload: object) -> None:
        self.agg = ArbitrationCaseAggregate()
        self.run("open_case", **open_payload)

    def run(self, command: str, /, **payload: object) -> ArbitrationCaseAggregate:
        self.agg.decide(Command(command, dict(payload), actor_id=ACTOR, organization_id=ORG))
        return self.agg

    def to_award(self, *, constituted_at: str = "2026-03-06") -> ArbitrationCaseAggregate:
        self.run("file_case")
        self.run("register_rfa", received_on="2026-02-02")
        self.run("add_party", role="claimant", name="Истец (демо)", party_id="c1")
        self.run(
            "add_party", role="respondent", name="Ответчик (демо)", party_id="r1", country="KZ"
        )
        self.run("nominate_arbitrator", side="claimant", arbitrator_name="A", arbitrator_id="a1")
        self.run("nominate_arbitrator", side="respondent", arbitrator_name="B", arbitrator_id="a2")
        self.run(
            "nominate_arbitrator",
            side="co_arbitrators",
            arbitrator_name="C",
            arbitrator_id="a3",
            law_degree=True,
        )
        self.run("constitute_tribunal", chair_id="a3", constituted_at=constituted_at)
        self.run("adopt_timetable", milestones=[{"code": "SoC", "due_at": "2026-04-01"}])
        self.run("open_submission_round", round_code="R1")
        self.run("start_deliberation")
        return self.run("issue_award")


@pytest.fixture
def intl_case() -> CaseDriver:
    return CaseDriver(party_countries=["RU", "KZ"], claim_amount="1000000")


@pytest.fixture
def domestic_case() -> CaseDriver:
    return CaseDriver(party_countries=["RU"], claim_amount="1000000")


def d(value: str) -> date:
    return date.fromisoformat(value)
