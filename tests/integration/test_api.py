from __future__ import annotations

from typing import Any

import httpx
import pytest

from arbiterforge.core.security import Role
from tests.integration.conftest import Tenant

API = "/api/v1"


async def post(
    client: httpx.AsyncClient,
    tenant: Tenant,
    path: str,
    json: Any = None,
    *,
    role: Role = Role.ADMIN,
    **kw: Any,
) -> httpx.Response:
    return await client.post(
        f"{API}{path}", json=json, headers={**tenant.headers(role), **kw.pop("headers", {})}, **kw
    )


async def get(
    client: httpx.AsyncClient, tenant: Tenant, path: str, *, role: Role = Role.ADMIN, **kw: Any
) -> httpx.Response:
    return await client.get(f"{API}{path}", headers=tenant.headers(role), **kw)


async def open_intl(client: httpx.AsyncClient, tenant: Tenant, **extra: Any) -> str:
    body = {
        "title": "<img src=x onerror=alert(1)>",
        "party_countries": ["RU", "KZ"],
        "claim_amount": "1000000",
        **extra,
    }
    response = await post(client, tenant, "/cases", body)
    assert response.status_code == 201, response.text
    return response.json()["case_id"]


async def test_health_auth_and_metrics(client: httpx.AsyncClient, tenant: Tenant) -> None:
    assert (await client.get(f"{API}/health/live")).json() == {"status": "ok"}
    assert (await client.get(f"{API}/health/ready")).json() == {"status": "ready"}
    bad = await client.post(
        f"{API}/auth/login", json={"email": "admin.1111@test.local", "password": "nope"}
    )
    assert bad.status_code == 401
    login = await client.post(
        f"{API}/auth/login", json={"email": "admin.1111@test.local", "password": "pw"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = await client.get(f"{API}/orgs/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["organization"]["id"] == tenant.org_id
    assert (await client.get(f"{API}/orgs/me")).status_code == 401
    garbage = await client.get(f"{API}/orgs/me", headers={"Authorization": "Bearer garbage"})
    assert garbage.status_code == 401
    assert (await client.post(f"{API}/auth/logout")).json() == {"status": "logged_out"}
    response = await client.get("/metrics")
    assert "arbiterforge_http_requests_total" in response.text
    assert login.headers["x-request-id"]


async def test_full_case_flow(client: httpx.AsyncClient, tenant: Tenant) -> None:
    case_id = await open_intl(client, tenant)
    path = f"/cases/{case_id}/commands"
    assert (
        await post(client, tenant, f"{path}/file", headers={"If-Match": '"1"'})
    ).status_code == 200
    stale = await post(client, tenant, f"{path}/register-rfa", headers={"If-Match": '"1"'})
    assert stale.status_code == 409
    assert stale.json()["actual_version"] == 2
    assert (
        await post(client, tenant, f"{path}/register-rfa", headers={"If-Match": "abc"})
    ).status_code == 400
    assert (
        await post(client, tenant, f"{path}/register-rfa", params={"received_on": "2026-02-02"})
    ).status_code == 200
    party = {"role": "respondent", "name": "Ответчик", "country": "KZ"}
    respondent = (await post(client, tenant, f"{path}/add-party", party)).json()["events"][0][
        "payload"
    ]["party_id"]
    claimant_body = {
        "role": "claimant",
        "name": "Истец",
        "inn": "0000123450",
        "ogrn": "1000000012341",
    }
    claimant = (await post(client, tenant, f"{path}/add-party", claimant_body)).json()["events"][0][
        "payload"
    ]["party_id"]
    bad_inn = await post(
        client, tenant, f"{path}/add-party", {**claimant_body, "inn": "0000123451"}
    )
    assert bad_inn.status_code == 400
    for side, law in (("claimant", False), ("respondent", False), ("co_arbitrators", True)):
        nominated = await post(
            client,
            tenant,
            f"{path}/nominate-arbitrator",
            {"side": side, "arbitrator_name": side, "law_degree": law},
        )
        assert nominated.status_code == 200
    tribunal = (await get(client, tenant, f"/cases/{case_id}/tribunal")).json()
    chair = tribunal["nominations"][2]["arbitrator_id"]
    constituted = await post(
        client,
        tenant,
        f"{path}/constitute-tribunal",
        {"chair_id": chair, "constituted_at": "2026-03-06"},
    )
    assert constituted.status_code == 200, constituted.text
    member = tribunal["nominations"][0]["arbitrator_id"]
    challenge = await post(
        client,
        tenant,
        f"{path}/challenge-arbitrator",
        {"arbitrator_id": member, "party_id": respondent},
    )
    challenge_id = challenge.json()["events"][0]["payload"]["challenge_id"]
    await post(
        client,
        tenant,
        f"{path}/decide-challenge",
        {"challenge_id": challenge_id, "upheld": False, "notified_on": "2026-03-20"},
    )
    await post(
        client,
        tenant,
        f"{path}/replace-arbitrator",
        {"arbitrator_id": member, "replacement_name": "Новый"},
    )
    await post(client, tenant, f"{path}/rule-on-jurisdiction", {"notified_on": "2026-03-25"})
    timetable = {
        "milestones": [{"code": "SoC", "due_at": "2026-04-01T00:00:00+03:00", "label": "Иск"}]
    }
    assert (await post(client, tenant, f"{path}/adopt-timetable", timetable)).status_code == 200
    await post(
        client,
        tenant,
        f"{path}/extend-milestone",
        {"milestone_code": "SoC", "new_due_at": "2026-04-15T00:00:00+03:00"},
    )
    await post(
        client,
        tenant,
        f"{path}/open-submission-round",
        {"round_code": "R1", "due_at": "2026-05-01T00:00:00+03:00"},
    )
    await post(
        client,
        tenant,
        f"{path}/file-submission",
        {"title": "Отзыв", "round_code": "R1"},
        role=Role.COUNSEL,
    )
    po = await post(
        client,
        tenant,
        f"{path}/issue-procedural-order",
        {"number": "ПП-1", "gist": "Видеоконференция", "request_ai_draft": True},
    )
    assert po.status_code == 200
    po_id = po.json()["events"][0]["payload"]["po_id"]
    hearing = await post(
        client,
        tenant,
        f"{path}/schedule-hearing",
        {"when": "2026-06-01T10:00:00+03:00", "format": "hybrid"},
    )
    hearing_id = hearing.json()["events"][0]["payload"]["hearing_id"]
    await post(client, tenant, f"{path}/mark-hearing-held", params={"hearing_id": hearing_id})
    await post(client, tenant, f"{path}/start-deliberation")
    await post(client, tenant, f"{path}/draft-award", {"kind": "final"})
    assert (
        await post(
            client,
            tenant,
            f"{path}/issue-award",
            {"kind": "final", "operative_summary": "Удовлетворить"},
        )
    ).status_code == 200
    for party_id, day in ((respondent, "2026-09-30"), (claimant, "2026-10-01")):
        await post(
            client, tenant, f"{path}/receive-award", {"party_id": party_id, "received_on": day}
        )
    correction = await post(
        client,
        tenant,
        f"{path}/request-correction",
        {"party_id": respondent, "requested_on": "2026-10-05"},
    )
    request_id = correction.json()["events"][0]["payload"]["request_id"]
    await post(
        client,
        tenant,
        f"{path}/decide-correction",
        {"request_id": request_id, "decided_on": "2026-10-20"},
    )
    deadlines = {
        d["key"]: d for d in (await get(client, tenant, f"/cases/{case_id}/deadlines")).json()
    }
    assert deadlines[f"deadline:set_aside:{respondent}"]["due_date"] == "2027-01-20"
    assert deadlines["deadline:court_challenge_review:" + respondent]["due_date"] == "2026-04-20"
    assert deadlines["deadline:court_jurisdiction_review:any"]["due_date"] == "2026-04-27"
    set_aside = await post(
        client, tenant, f"{path}/file-set-aside", {"party_id": respondent, "filed_on": "2027-01-18"}
    )
    assert set_aside.json()["events"][0]["payload"]["timely"] is True
    resolved = await post(client, tenant, f"{path}/resolve-set-aside", {"outcome": "dismissed"})
    assert resolved.json()["current_status"] == "Closed"
    case = (await get(client, tenant, f"/cases/{case_id}")).json()
    assert case["regime"] == "INTERNATIONAL"
    assert case["legal"]["applicable_law"].startswith("Закон РФ")
    timeline = (await get(client, tenant, f"/cases/{case_id}/timeline")).json()
    assert timeline[-1]["event_type"] == "ChallengeResolved"
    listing = (await get(client, tenant, "/cases")).json()
    assert [c["case_id"] for c in listing] == [case_id]
    calendar = (
        await get(
            client,
            tenant,
            "/calendar",
            params={
                "kind": "statutory_deadline",
                "from": "2026-01-01T00:00:00Z",
                "to": "2027-12-31T00:00:00Z",
            },
        )
    ).json()
    assert calendar
    assert all(e["kind"] == "statutory_deadline" for e in calendar)
    html = (await get(client, tenant, f"/exports/timeline-packs/{case_id}")).text
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    summary = await post(client, tenant, f"/procedural-orders/{po_id}/summarize-suggest")
    assert summary.json()["requires_human_review"] is True
    assert summary.json()["human_accepted"] is False
    forbidden = await post(client, tenant, f"/procedural-orders/{po_id}/accept", role=Role.COUNSEL)
    assert forbidden.status_code == 403
    accepted = await post(
        client, tenant, f"/procedural-orders/{po_id}/accept", role=Role.CASE_MANAGER
    )
    assert accepted.json()["human_accepted"] is True
    audit = (await get(client, tenant, "/admin/audit/verify", role=Role.AUDITOR_READONLY)).json()
    assert audit["valid"] is True
    assert audit["checked"] >= 8
    rebuilt = (await post(client, tenant, "/admin/projections/rebuild")).json()
    assert rebuilt["cases"] == 1
    lag = (await get(client, tenant, "/admin/outbox/lag")).json()
    assert lag["pending_events"] == len(timeline)


async def test_domestic_rules_via_api(client: httpx.AsyncClient, tenant: Tenant) -> None:
    refused = await post(
        client,
        tenant,
        "/cases",
        {"dispute_category": "corporate_internal", "institution": "AD_HOC"},
    )
    assert refused.status_code == 400
    assert "APK_225_1_3" in refused.json()["basis"]
    assert refused.json()["norms"][0]["quote"]
    final_adhoc = await post(
        client, tenant, "/cases", {"institution": "AD_HOC", "final_award_agreed": True}
    )
    assert final_adhoc.status_code == 400
    case = await post(client, tenant, "/cases", {"institution": "AD_HOC"})
    case_id = case.json()["case_id"]
    await post(client, tenant, f"/cases/{case_id}/commands/file")
    await post(
        client,
        tenant,
        f"/cases/{case_id}/commands/register-rfa",
        params={"received_on": "2026-01-30"},
    )
    deadlines = (await get(client, tenant, f"/cases/{case_id}/deadlines")).json()
    assert deadlines[0]["code"] == "respondent_nomination"
    assert deadlines[0]["due_date"] == "2026-03-02"
    assert deadlines[0]["label"] == "Назначение арбитра ответчиком"
    unqualified = await post(
        client,
        tenant,
        f"/cases/{case_id}/commands/constitute-tribunal",
        {"composition": "sole", "members": [{"arbitrator_id": "x", "name": "X"}]},
    )
    assert unqualified.status_code == 400
    assert "DOM_11_6" in unqualified.json()["basis"]
    wrong_state = await post(client, tenant, f"/cases/{case_id}/commands/issue-award", {})
    assert wrong_state.status_code == 422
    terminated = await post(
        client, tenant, f"/cases/{case_id}/commands/terminate", params={"reason": "отказ от иска"}
    )
    assert terminated.json()["current_status"] == "Terminated"
    validation = await post(client, tenant, "/cases", {"claim_currency": "rub"})
    assert validation.status_code == 422


async def test_tenant_isolation_and_rbac(
    client: httpx.AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    case_id = await open_intl(client, tenant)
    for path in ("", "/timeline", "/tribunal", "/deadlines"):
        assert (await get(client, other_tenant, f"/cases/{case_id}{path}")).status_code == 404
    assert (await post(client, other_tenant, f"/cases/{case_id}/commands/file")).status_code == 404
    assert (
        await get(client, other_tenant, f"/exports/timeline-packs/{case_id}")
    ).status_code == 404
    assert (await get(client, other_tenant, "/cases")).json() == []
    assert (
        await post(client, tenant, f"/cases/{case_id}/commands/file", role=Role.AUDITOR_READONLY)
    ).status_code == 403
    assert (
        await post(client, tenant, "/admin/projections/rebuild", role=Role.COUNSEL)
    ).status_code == 403
    assert (
        await get(client, tenant, "/admin/outbox/lag", role=Role.CASE_MANAGER)
    ).status_code == 403
    assert (
        await post(client, tenant, "/procedural-orders/missing/summarize-suggest")
    ).status_code == 404
    assert (await post(client, tenant, "/procedural-orders/missing/accept")).status_code == 404


async def test_legal_endpoints(client: httpx.AsyncClient, tenant: Tenant) -> None:
    term = await post(
        client,
        tenant,
        "/legal/deadlines/compute",
        {"start": "2026-12-25", "amount": 5, "unit": "days", "rule": "APK_113_114"},
    )
    assert term.json()["due_date"] == "2027-01-12"
    regime = await post(
        client, tenant, "/legal/regime", {"seat_country": "RU", "party_countries": ["RU", "CN"]}
    )
    assert regime.json()["regime"] == "INTERNATIONAL"
    assert regime.json()["norms"][0]["code"] == "ICA_1_3"
    arb = await post(
        client,
        tenant,
        "/legal/arbitrability",
        {"category": "procurement_223fz", "institution": "AD_HOC"},
    )
    assert arb.json()["admissible"] is False
    check = await post(
        client,
        tenant,
        "/legal/tribunal-check",
        {
            "composition": "three",
            "members": [{"arbitrator_id": "a", "name": "A"}, {"arbitrator_id": "b", "name": "B"}],
            "regime": "INTERNATIONAL",
        },
    )
    assert "member_count_mismatch" in check.json()["problems"]
    days = await get(client, tenant, "/legal/working-days/2027")
    assert "2027-11-05" in days.json()["non_working_weekdays"]
    assert (await get(client, tenant, "/legal/working-days/2031")).status_code == 422
    norms = (await get(client, tenant, "/legal/norms")).json()
    assert {"APK_230_4", "ICA_34_3", "DOM_45_10"} <= {n["code"] for n in norms}
    beyond = await post(
        client,
        tenant,
        "/legal/deadlines/compute",
        {"start": "2027-12-20", "amount": 30, "unit": "days"},
    )
    assert beyond.status_code == 422


@pytest.mark.parametrize("path", ["/legal/norms", "/calendar", "/cases"])
async def test_reads_require_token(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(f"{API}{path}")).status_code == 401
