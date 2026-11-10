from __future__ import annotations

from datetime import UTC, date, datetime

from arbiterforge.infrastructure.projections.builder import build_case_projection, parse_dt
from tests.conftest import CaseDriver


def test_projection_covers_status_tribunal_calendar(intl_case: CaseDriver) -> None:
    intl_case.to_award()
    intl_case.run("receive_award", party_id="r1", received_on="2026-09-30")
    projection = build_case_projection(intl_case.agg.state.history)
    assert projection.status["current_status"] == "AwardIssued"
    assert projection.status["regime"] == "INTERNATIONAL"
    assert projection.status["extra"]["dispute_category"] == "commercial"
    assert projection.tribunal["constituted"] is True
    assert projection.tribunal["chair_id"] == "a3"
    kinds = {row["kind"] for row in projection.calendar}
    assert kinds == {"milestone", "submission_round", "statutory_deadline"}
    deadline = next(r for r in projection.calendar if r["entry_key"] == "deadline:set_aside:r1")
    assert deadline["due_at"] == datetime(2026, 12, 30, tzinfo=UTC)
    assert deadline["label"] == "Заявление об отмене арбитражного решения"


def test_projection_is_pure_function_of_history(intl_case: CaseDriver) -> None:
    intl_case.to_award()
    history = intl_case.agg.state.history
    assert build_case_projection(history) == build_case_projection(list(history))
    partial = build_case_projection(history[:5])
    assert partial.status["version"] == 5


def test_hearing_and_round_completion() -> None:
    driver = CaseDriver(party_countries=["CN"])
    driver.run("file_case")
    driver.run("register_rfa")
    driver.run("nominate_arbitrator", side="institution", arbitrator_name="S")
    driver.run("constitute_tribunal", composition="sole")
    driver.run("adopt_timetable", milestones=[{"code": "A", "due_at": "2026-05-01"}])
    driver.run("open_submission_round", round_code="R1", due_at="2026-05-10")
    driver.run("file_submission", round_code="R1", title="T", filed_at="2026-05-09T10:00:00Z")
    driver.run("schedule_hearing", when="2026-06-01T10:00:00+03:00", hearing_id="h1")
    driver.run("mark_hearing_held", hearing_id="h1", held_at="2026-06-01T15:00:00+03:00")
    rows = {r["entry_key"]: r for r in build_case_projection(driver.agg.state.history).calendar}
    assert rows["round:R1"]["completed_at"] == datetime(2026, 5, 9, 10, tzinfo=UTC)
    assert rows["hearing:h1"]["completed_at"] is not None


def test_parse_dt_variants() -> None:
    assert parse_dt(None) is None
    assert parse_dt("") is None
    assert parse_dt(date(2026, 1, 2)) == datetime(2026, 1, 2, tzinfo=UTC)
    assert parse_dt(datetime(2026, 1, 2)) == datetime(2026, 1, 2, tzinfo=UTC)
    assert parse_dt("2026-01-02") == datetime(2026, 1, 2, tzinfo=UTC)
    assert parse_dt("2026-01-02T03:00:00Z").tzinfo is not None
