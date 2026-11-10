from __future__ import annotations

import json
import logging
from datetime import date

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from arbiterforge.application import legal
from arbiterforge.core.config import DEV_AUDIT_SECRET, DEV_TOKEN_SECRET, Settings
from arbiterforge.core.logging import configure_logging, get_logger
from arbiterforge.core.security import (
    InvalidTokenError,
    Role,
    create_access_token,
    decode_access_token,
    has_permission,
    hash_password,
    verify_password,
)
from arbiterforge.domain.arbitrability import DisputeCategory
from arbiterforge.domain.regime import RegimeInput
from arbiterforge.domain.terms import ComputationRule, TermUnit
from arbiterforge.domain.value_objects import (
    EventEnvelope,
    Institution,
    Regime,
    TribunalComposition,
)
from arbiterforge.infrastructure.exporters.timeline import build_timeline_html
from arbiterforge.infrastructure.ollama import assistant


def test_password_roundtrip() -> None:
    hashed = hash_password("s3cret!")
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("s3cret!", "not-a-hash")


def test_token_roundtrip_and_failures() -> None:
    token = create_access_token({"sub": "u", "email": "a@b", "role": "ADMIN", "org_id": "o"})
    payload = decode_access_token(token)
    assert (payload.sub, payload.org_id) == ("u", "o")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token[:-3] + "AAA")
    expired = create_access_token(
        {"sub": "u", "email": "a@b", "role": "ADMIN", "org_id": "o"}, ttl_minutes=-1
    )
    with pytest.raises(InvalidTokenError, match="expired"):
        decode_access_token(expired)


def test_rbac() -> None:
    assert has_permission(Role.ADMIN, "admin")
    assert not has_permission(Role.AUDITOR_READONLY, "case:write")
    assert has_permission(Role.CASE_MANAGER, "po:accept")
    assert not has_permission("GHOST", "case:read")


def test_prod_rejects_dev_secrets() -> None:
    # Явно передаём dev-секреты: в Docker env уже могут быть сгенерированные значения.
    with pytest.raises(PydanticValidationError):
        Settings(env="prod", token_secret=DEV_TOKEN_SECRET, audit_hmac_secret=DEV_AUDIT_SECRET)
    cfg = Settings(env="prod", token_secret="x" * 40, audit_hmac_secret="y" * 40)
    assert cfg.broker_url == cfg.redis_url
    assert Settings(cors_allow_origins="a, b,").cors_origins == ["a", "b"]
    assert Settings(celery_broker_url="redis://b").broker_url == "redis://b"


def test_timeline_export_escapes_html() -> None:
    evil = EventEnvelope(
        "e1",
        "c1",
        "ArbitrationCase",
        1,
        "CaseOpened",
        {"title": "<script>alert(1)</script>"},
        "2026-01-01T00:00:00+00:00",
        None,
        {},
    )
    html = build_timeline_html(
        "<b>c1</b>", [evil], [{"code": "<i>x</i>", "party": "p", "due_date": None, "basis": ["A"]}]
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;c1&lt;/b&gt;" in html
    assert "&lt;i&gt;x&lt;/i&gt;" in html


async def test_ollama_success_and_fallback() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == assistant.system_prompt()
        return httpx.Response(200, json={"message": {"content": " Краткое резюме. "}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(ok), base_url="http://o") as client:
        text = await assistant.draft_procedural_order_summary("gist", client=client)
    assert text == assistant.FALLBACK_PREFIX + "Краткое резюме."

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(broken), base_url="http://o"
    ) as client:
        text = await assistant.draft_procedural_order_summary("x" * 400, client=client)
    assert text.startswith(assistant.FALLBACK_PREFIX)
    assert text.endswith("…")

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "  "}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(empty), base_url="http://o"
    ) as client:
        assert await assistant.draft_procedural_order_summary("g", client=client) == (
            assistant.FALLBACK_PREFIX + "g"
        )


async def test_ollama_owns_client_when_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARBITERFORGE_OLLAMA_BASE_URL", "http://127.0.0.1:9")
    from arbiterforge.core.config import get_settings

    get_settings.cache_clear()
    try:
        text = await assistant.draft_procedural_order_summary("g")
    finally:
        get_settings.cache_clear()
    assert text == assistant.FALLBACK_PREFIX + "g"


def test_legal_service() -> None:
    term = legal.compute_term(date(2026, 12, 25), 5, TermUnit.DAYS, ComputationRule.APK)
    assert term["due_date"] == "2027-01-12"
    assert {n["code"] for n in term["norms"]} == {"APK_113", "APK_114", "TK_112"}
    assert legal.regime(RegimeInput(seat_country="DE"))["regime"] == "FOREIGN_SEAT"
    assert (
        legal.arbitrability(
            DisputeCategory.PRIVATIZATION,
            Institution.ICAC_MKAS,
            seat_country="RU",
            all_participants_signed=False,
            sanctions_involved=False,
        )["admissible"]
        is False
    )
    check = legal.tribunal(
        TribunalComposition.SOLE,
        [{"arbitrator_id": "a", "name": "A", "law_degree": True}],
        institution=Institution.AD_HOC,
        regime_value=Regime.DOMESTIC,
        claim_amount=None,
        claim_currency="RUB",
        chair_requirement_waived=False,
    )
    assert check["ok"]
    assert legal.working_days(2026)["act"].endswith("№ 1466")
    assert len(legal.all_norms()) >= 40


def test_logging_masks_pii(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(enable_masking=True, json=True)
    get_logger("t").info("login email=someone@example.com inn=0000123450")
    out = capsys.readouterr().out
    assert "someone@example.com" not in out
    assert "0000123450" not in out
    configure_logging(enable_masking=False, json=False, log_level="WARNING")
    assert logging.getLogger().level == logging.WARNING
