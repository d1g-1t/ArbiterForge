from __future__ import annotations

from datetime import date

from arbiterforge.domain.calendar import RussianWorkCalendar
from arbiterforge.domain.deadlines import (
    THIRTY_DAYS,
    compute_case_deadlines,
    make_deadline,
    parse_day,
)
from tests.conftest import CaseDriver


def by_key(driver: CaseDriver) -> dict[str, dict]:
    return {d["key"]: d for d in driver.agg.deadlines()}


def test_international_post_award_deadlines(intl_case: CaseDriver) -> None:
    intl_case.to_award()
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    found = by_key(intl_case)
    assert found["deadline:arbitrator_challenge:any"]["due_date"] == "2026-03-23"
    assert found["deadline:correction_request:r1"]["due_date"] == "2026-10-30"
    assert found["deadline:correction_request:r1"]["basis"] == ["ICA_33_1"]
    assert found["deadline:set_aside:r1"]["due_date"] == "2026-12-30"
    assert found["deadline:set_aside:r1"]["basis"] == ["ICA_34_3", "APK_230_4"]
    assert found["deadline:set_aside:r1"]["dispositive"] is False


def test_set_aside_recomputed_after_correction_only_for_international(
    intl_case: CaseDriver,
) -> None:
    intl_case.to_award()
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    intl_case.run("request_correction", party_id="r1", requested_on="2026-10-05", request_id="q1")
    intl_case.run("decide_correction", request_id="q1", decided_on="2026-10-20")
    found = by_key(intl_case)
    assert found["deadline:correction_request:r1"]["completed_on"] == "2026-10-05"
    assert found["deadline:tribunal_correction_decision:tribunal"]["completed_on"] == "2026-10-20"
    assert found["deadline:set_aside:r1"]["due_date"] == "2027-01-20"
    assert found["deadline:set_aside:r1"]["note"] == "recomputed_after_art33"


def test_domestic_uses_382_and_storage(domestic_case: CaseDriver) -> None:
    domestic_case.to_award()
    domestic_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    domestic_case.run(
        "request_correction",
        party_id="r1",
        requested_on="2026-10-01",
        kind="additional_award",
        request_id="q",
    )
    domestic_case.run("decide_correction", request_id="q", decided_on="2026-10-10")
    domestic_case.run("close_case", closed_at="2026-11-30T12:00:00+00:00")
    found = by_key(domestic_case)
    assert found["deadline:set_aside:r1"]["basis"] == ["APK_230_4"]
    assert found["deadline:set_aside:r1"]["due_date"] == "2026-12-30"
    assert found["deadline:tribunal_additional_award_decision:tribunal"]["due_date"] == "2026-11-30"
    assert found["deadline:additional_award_request:r1"]["completed_on"] == "2026-10-01"
    assert found["deadline:case_file_storage:tribunal"]["due_date"] == "2026-12-30"
    assert found["deadline:case_file_storage:tribunal"]["basis"] == ["DOM_39_1"]


def test_final_award_suppresses_set_aside() -> None:
    driver = CaseDriver(party_countries=["RU", "KZ"], final_award_agreed=True)
    driver.to_award()
    driver.run("receive_award", party_id="r1", received_on="2026-09-30")
    assert "deadline:set_aside:r1" not in by_key(driver)


def test_ad_hoc_nomination_deadline_by_regime() -> None:
    intl = CaseDriver(institution="AD_HOC", party_countries=["RU", "CN"])
    intl.run("file_case")
    intl.run("register_rfa", received_on="2026-01-30")
    dom = CaseDriver(institution="AD_HOC")
    dom.run("file_case")
    dom.run("register_rfa", received_on="2026-01-30")
    assert by_key(intl)["deadline:respondent_nomination:respondent"]["due_date"] == "2026-03-02"
    assert by_key(dom)["deadline:respondent_nomination:respondent"]["due_date"] == "2026-03-02"
    assert by_key(dom)["deadline:respondent_nomination:respondent"]["basis"] == ["DOM_11_3"]
    dom.run("nominate_arbitrator", side="respondent", arbitrator_name="R")
    assert by_key(dom)["deadline:respondent_nomination:respondent"]["completed_on"]
    sole = CaseDriver(institution="AD_HOC", agreed_composition="sole")
    sole.run("file_case")
    sole.run("register_rfa", received_on="2026-01-30")
    assert by_key(sole) == {}


def test_challenge_and_jurisdiction_court_windows() -> None:
    driver = CaseDriver(party_countries=["RU", "KZ"])
    driver.run("file_case")
    driver.run("register_rfa")
    driver.run("add_party", role="claimant", name="C", party_id="c1")
    for i, side in enumerate(["claimant", "respondent", "co_arbitrators"]):
        driver.run("nominate_arbitrator", side=side, arbitrator_name=f"N{i}", arbitrator_id=f"a{i}")
    driver.run("constitute_tribunal", chair_id="a2", constituted_at="2026-04-01")
    driver.run(
        "challenge_arbitrator",
        arbitrator_id="a1",
        party_id="c1",
        filed_on="2026-04-10",
        challenge_id="ch",
    )
    driver.run(
        "decide_arbitrator_challenge", challenge_id="ch", upheld=False, notified_on="2026-04-20"
    )
    driver.run("rule_on_jurisdiction", has_jurisdiction=True, notified_on="2026-04-30")
    found = by_key(driver)
    assert found["deadline:arbitrator_challenge:any"]["completed_on"] == "2026-04-10"
    assert found["deadline:court_challenge_review:c1"]["due_date"] == "2026-05-20"
    assert found["deadline:court_jurisdiction_review:any"]["due_date"] == "2026-06-01"


def test_court_review_exclusion_for_institutional_international() -> None:
    driver = CaseDriver(party_countries=["RU", "KZ"], court_review_excluded=True)
    driver.run("file_case")
    driver.run("register_rfa")
    driver.run("add_party", role="claimant", name="C", party_id="c1")
    driver.run("nominate_arbitrator", side="institution", arbitrator_name="S", arbitrator_id="s")
    driver.run("constitute_tribunal", composition="sole", constituted_at="2026-04-01")
    driver.run("challenge_arbitrator", arbitrator_id="s", party_id="c1", challenge_id="x")
    driver.run(
        "decide_arbitrator_challenge", challenge_id="x", upheld=False, notified_on="2026-04-20"
    )
    assert not any(k.startswith("deadline:court_challenge_review") for k in by_key(driver))


def test_foreign_seat_has_no_local_deadlines() -> None:
    driver = CaseDriver(seat={"city": "Dubai", "country": "AE"}, institution="AD_HOC")
    driver.run("file_case")
    driver.run("register_rfa", received_on="2026-03-01")
    assert by_key(driver) == {}


def test_set_aside_filed_marks_completion(intl_case: CaseDriver) -> None:
    intl_case.to_award()
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    intl_case.run("file_set_aside", party_id="r1", filed_on="2027-01-15")
    assert intl_case.agg.state.history[-1].payload["timely"] is False
    assert by_key(intl_case)["deadline:set_aside:r1"]["completed_on"] == "2027-01-15"


def test_calendar_gap_reported_not_raised() -> None:
    narrow = RussianWorkCalendar(transfers={2026: ()})
    late = make_deadline(
        "x", "p", date(2026, 12, 20), THIRTY_DAYS, ("ICA_33_1",), dispositive=True, cal=narrow
    )
    assert late.due_date is None
    assert late.note == "calendar_not_covered:2027"
    assert late.to_dict()["due_date"] is None


def test_parse_day_and_empty_history() -> None:
    assert parse_day(None) is None
    assert parse_day("") is None
    assert parse_day(date(2026, 1, 1)) == date(2026, 1, 1)
    assert parse_day("2026-02-03T10:00:00+03:00") == date(2026, 2, 3)
    assert compute_case_deadlines([]) == []
