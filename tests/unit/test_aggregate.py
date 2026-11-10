from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from arbiterforge.domain.aggregate import DECIDERS, ArbitrationCaseAggregate, Command
from arbiterforge.domain.events import EventType
from arbiterforge.domain.exceptions import ConcurrencyError, InvalidTransitionError, ValidationError
from arbiterforge.domain.state_machine import (
    ALLOWED,
    NEXT_STATUS,
    assert_transition_allowed,
    next_status,
)
from arbiterforge.domain.value_objects import CaseStatus, Regime
from tests.conftest import ORG, CaseDriver


def test_open_case_records_legal_analysis() -> None:
    driver = CaseDriver(party_countries=["RU", "KZ"], claim_amount="10")
    payload = driver.agg.state.history[0].payload
    assert payload["regime"] == "INTERNATIONAL"
    assert payload["regime_reasons"] == ["party_abroad"]
    assert payload["arbitrability"]["outcome"] == "ARBITRABLE"
    assert driver.agg.state.organization_id == ORG
    assert driver.agg.state.regime is Regime.INTERNATIONAL


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"institution": "NOPE"}, "institution"),
        ({"dispute_category": "bankruptcy"}, "not_arbitrable"),
        ({"claim_amount": "-5"}, "claim amount"),
        ({"claim_amount": "abc"}, "claim amount"),
        ({"institution": "AD_HOC", "final_award_agreed": True}, "Final award"),
        ({"institution": "AD_HOC", "court_review_excluded": True}, "court review"),
        ({"agreed_composition": "five"}, "agreed_composition"),
    ],
)
def test_open_case_validation(payload: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        CaseDriver(**payload)


def test_full_lifecycle(intl_case: CaseDriver) -> None:
    agg = intl_case.to_award()
    assert agg.state.status is CaseStatus.AWARD_ISSUED
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    intl_case.run("file_set_aside", party_id="r1", filed_on="2026-10-15", court="АС г. Москвы")
    assert agg.state.status is CaseStatus.SET_ASIDE_CHALLENGE
    assert agg.state.history[-1].payload["timely"] is True
    intl_case.run("resolve_set_aside", outcome="dismissed")
    assert agg.state.status is CaseStatus.CLOSED
    assert [e.version for e in agg.state.history] == list(range(1, agg.state.version + 1))


def test_replay_equals_live_state(intl_case: CaseDriver) -> None:
    live = intl_case.to_award()
    replayed = ArbitrationCaseAggregate.from_history(live.state.aggregate_id, live.state.history)
    assert replayed.state.status == live.state.status
    assert replayed.state.tribunal == live.state.tribunal
    assert replayed.state.parties == live.state.parties
    assert replayed.deadlines() == live.deadlines()


def test_concurrency_guard(intl_case: CaseDriver) -> None:
    with pytest.raises(ConcurrencyError) as exc:
        intl_case.agg.decide(Command("file_case", {}, organization_id=ORG, expected_version=0))
    assert (exc.value.expected, exc.value.actual) == (0, 1)


def test_invalid_transitions(intl_case: CaseDriver) -> None:
    with pytest.raises(InvalidTransitionError):
        intl_case.run("issue_award")
    with pytest.raises(InvalidTransitionError, match="already opened"):
        intl_case.run("open_case")
    with pytest.raises(ValidationError, match="Unknown command"):
        intl_case.run("teleport")


def test_party_and_tribunal_validation(intl_case: CaseDriver) -> None:
    intl_case.run("file_case")
    intl_case.run("register_rfa")
    with pytest.raises(ValidationError, match="INN"):
        intl_case.run("add_party", role="claimant", name="X", inn="0000123451")
    with pytest.raises(ValidationError, match="OGRN"):
        intl_case.run("add_party", role="claimant", name="X", ogrn="1000000012342")
    with pytest.raises(ValidationError, match="role"):
        intl_case.run("add_party", role="judge", name="X")
    with pytest.raises(ValidationError, match="name"):
        intl_case.run("add_party", role="claimant", name="")
    intl_case.run("add_party", role="respondent", name="Foreign", country="kz", inn="123")
    with pytest.raises(ValidationError, match="Arbitrator name"):
        intl_case.run("nominate_arbitrator", side="claimant", arbitrator_name="")
    intl_case.run("nominate_arbitrator", side="claimant", arbitrator_name="A", arbitrator_id="a1")
    intl_case.run("nominate_arbitrator", side="respondent", arbitrator_name="B", arbitrator_id="a2")
    with pytest.raises(ValidationError, match="member_count_mismatch"):
        intl_case.run("constitute_tribunal", chair_id="a1")


def test_domestic_tribunal_needs_qualified_chair(domestic_case: CaseDriver) -> None:
    domestic_case.run("file_case")
    domestic_case.run("register_rfa")
    members = [
        {"arbitrator_id": "x", "name": "X"},
        {"arbitrator_id": "y", "name": "Y", "law_degree": True},
        {"arbitrator_id": "z", "name": "Z"},
    ]
    with pytest.raises(ValidationError) as exc:
        domestic_case.run("constitute_tribunal", members=members, chair_id="x")
    assert "DOM_11_6" in exc.value.basis
    domestic_case.run(
        "constitute_tribunal", members=members, chair_id="x", chair_requirement_waived=True
    )
    payload = domestic_case.agg.state.history[-1].payload
    assert payload["advisories"] == ["icac_domestic_sole_arbitrator_default"]


def test_challenge_replace_and_errors() -> None:
    agg = CaseDriver(party_countries=["CN"])
    agg.run("file_case")
    agg.run("register_rfa")
    agg.run("add_party", role="claimant", name="C", party_id="c1")
    agg.run("nominate_arbitrator", side="institution", arbitrator_name="S", arbitrator_id="s")
    agg.run("constitute_tribunal", composition="sole")
    with pytest.raises(ValidationError, match="not a tribunal member"):
        agg.run("challenge_arbitrator", arbitrator_id="ghost", party_id="c1")
    with pytest.raises(ValidationError, match="not a party"):
        agg.run("challenge_arbitrator", arbitrator_id="s", party_id="ghost")
    agg.run("challenge_arbitrator", arbitrator_id="s", party_id="c1", challenge_id="ch")
    with pytest.raises(ValidationError, match="Unknown challenge"):
        agg.run("decide_arbitrator_challenge", challenge_id="nope", upheld=True)
    agg.run("decide_arbitrator_challenge", challenge_id="ch", upheld=True)
    with pytest.raises(ValidationError, match="not a tribunal member"):
        agg.run("replace_arbitrator", arbitrator_id="ghost", replacement_name="N")
    agg.run("replace_arbitrator", arbitrator_id="s", replacement_name="New", replacement_id="n")
    assert agg.agg.state.tribunal["members"][0]["arbitrator_id"] == "n"
    assert agg.agg.state.tribunal["members"][0]["is_chair"] is True


def test_timetable_rules() -> None:
    driver = CaseDriver(party_countries=["CN"])
    driver.run("file_case")
    driver.run("register_rfa")
    driver.run("nominate_arbitrator", side="institution", arbitrator_name="S")
    driver.run("constitute_tribunal", composition="sole")
    with pytest.raises(ValidationError, match="milestones"):
        driver.run("adopt_timetable", milestones=[])
    with pytest.raises(ValidationError, match="unique"):
        driver.run("adopt_timetable", milestones=[{"code": "A"}, {"code": "A"}])
    driver.run("adopt_timetable", milestones=[{"code": "A", "due_at": "2026-05-01"}])
    with pytest.raises(ValidationError, match="Unknown milestone"):
        driver.run("extend_milestone", milestone_code="B", new_due_at="2026-06-01")
    driver.run("extend_milestone", milestone_code="A", new_due_at="2026-06-01", reason="ПП-3")
    assert driver.agg.state.milestones[0]["due_at"] == "2026-06-01"
    driver.run("open_submission_round", round_code="R1")
    driver.run("schedule_hearing", when="2026-07-01T10:00:00+03:00", format="hybrid")
    with pytest.raises(ValidationError, match="format"):
        driver.run("schedule_hearing", when="x", format="moon")
    driver.run("issue_procedural_order", number="1")
    driver.run("mark_hearing_held")
    driver.run("start_deliberation")
    driver.run("terminate_case", reason="settlement")
    assert driver.agg.state.status is CaseStatus.TERMINATED


def test_post_award_validation(intl_case: CaseDriver) -> None:
    intl_case.to_award()
    with pytest.raises(ValidationError, match="Unknown party"):
        intl_case.run("receive_award", party_id="ghost")
    with pytest.raises(ValidationError, match="not received"):
        intl_case.run("request_correction", party_id="r1")
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    with pytest.raises(ValidationError, match="already recorded"):
        intl_case.run("receive_award", party_id="r1")
    with pytest.raises(ValidationError, match="predates"):
        intl_case.run("request_correction", party_id="r1", requested_on="2026-09-01")
    with pytest.raises(ValidationError, match="Invalid date"):
        intl_case.run("request_correction", party_id="r1", requested_on="not-a-date")
    with pytest.raises(ValidationError, match="Unknown correction"):
        intl_case.run("decide_correction", request_id="nope")
    with pytest.raises(ValidationError, match="Unknown party"):
        intl_case.run("file_set_aside", party_id="ghost")
    with pytest.raises(ValidationError, match="outcome"):
        intl_case.run("resolve_set_aside", outcome="maybe")


def test_final_award_cannot_be_set_aside() -> None:
    driver = CaseDriver(party_countries=["CN"], final_award_agreed=True)
    driver.to_award()
    driver.run("receive_award", party_id="r1")
    with pytest.raises(ValidationError) as exc:
        driver.run("file_set_aside", party_id="r1")
    assert exc.value.basis == ("ICA_34_1", "DOM_40")


def test_state_machine_tables_are_consistent() -> None:
    assert set(ALLOWED) | {EventType.CASE_OPENED} == set(EventType)
    assert set(NEXT_STATUS) <= set(EventType)
    with pytest.raises(InvalidTransitionError, match="no CaseOpened"):
        assert_transition_allowed(None, EventType.CASE_FILED)
    with pytest.raises(InvalidTransitionError, match="Unknown event"):
        assert_transition_allowed(CaseStatus.INTAKE, "Bogus")
    assert (
        next_status(CaseStatus.TRIBUNAL_PENDING, EventType.PARTY_ADDED)
        is CaseStatus.TRIBUNAL_PENDING
    )
    assert set(DECIDERS) >= {"open_case", "file_set_aside", "close_case"}


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(sorted(set(DECIDERS) - {"open_case"})), max_size=25))
def test_random_command_sequences_keep_invariants(names: list[str]) -> None:
    driver = CaseDriver(party_countries=["RU", "KZ"])
    agg = driver.agg
    samples = {
        "add_party": {"role": "claimant", "name": "P", "party_id": "p1"},
        "nominate_arbitrator": {
            "side": "institution",
            "arbitrator_name": "S",
            "arbitrator_id": "s",
        },
        "constitute_tribunal": {"composition": "sole"},
        "adopt_timetable": {"milestones": [{"code": "A", "due_at": "2026-05-01"}]},
        "open_submission_round": {"round_code": "R"},
        "file_submission": {"title": "T"},
        "issue_procedural_order": {"number": "1"},
        "schedule_hearing": {"when": "2026-06-01T10:00:00+03:00"},
        "receive_award": {"party_id": "p1", "received_on": "2026-09-01"},
        "file_set_aside": {"party_id": "p1", "filed_on": "2026-10-01"},
        "resolve_set_aside": {"outcome": "dismissed"},
        "extend_milestone": {"milestone_code": "A", "new_due_at": "2026-06-01"},
    }
    for name in names:
        before = (agg.state.version, agg.state.status)
        try:
            driver.run(name, **samples.get(name, {}))
        except (InvalidTransitionError, ValidationError, KeyError):
            assert (agg.state.version, agg.state.status) == before
        else:
            assert agg.state.version == before[0] + 1
    replay = ArbitrationCaseAggregate.from_history(agg.state.aggregate_id, agg.state.history)
    assert replay.state.status == agg.state.status
    assert replay.deadlines() == agg.deadlines()
