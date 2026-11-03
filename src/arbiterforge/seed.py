from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.application.commands import CaseCommandService
from arbiterforge.core.config import Settings, get_settings
from arbiterforge.core.logging import configure_logging, get_logger
from arbiterforge.core.security import Role, hash_password
from arbiterforge.infrastructure.db.models import OrganizationModel, UserModel
from arbiterforge.infrastructure.db.session import make_engine, make_sessionmaker

logger = get_logger(__name__)

DEMO_EMAIL = "admin@arbiterforge.local"
DEMO_PASSWORD = "ChangeMe123!"
DEMO_ORG = {
    "name": "АО «Демо Логистик» (вымышленная организация)",
    "inn": "0000123450",
    "ogrn": "1000000012341",
}
DEMO_USERS = (
    (DEMO_EMAIL, Role.ADMIN, "Администратор (демо)"),
    ("manager@arbiterforge.local", Role.CASE_MANAGER, "Кейс-менеджер (демо)"),
    ("counsel@arbiterforge.local", Role.COUNSEL, "Представитель (демо)"),
    ("arbitrator@arbiterforge.local", Role.ARBITRATOR_READONLY, "Арбитр, только чтение (демо)"),
    ("auditor@arbiterforge.local", Role.AUDITOR_READONLY, "Аудитор (демо)"),
)


class _Runner:
    def __init__(self, service: CaseCommandService, actor: str, org: str) -> None:
        self.service = service
        self.actor = actor
        self.org = org
        self.case_id: str | None = None
        self.version = 0

    async def __call__(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.service.execute(
            case_id=self.case_id,
            command_name=name,
            payload=payload,
            actor_id=self.actor,
            organization_id=self.org,
            expected_version=self.version,
        )
        self.case_id = result["case_id"]
        self.version = result["version"]
        return result


async def seed_demo(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    existing = await session.execute(select(UserModel).where(UserModel.email == DEMO_EMAIL))
    if existing.scalar_one_or_none() is not None:
        return {"status": "already_seeded"}
    org = OrganizationModel(id=str(uuid.uuid4()), **DEMO_ORG)
    session.add(org)
    await session.flush()
    admin_id = ""
    password_hash = hash_password(DEMO_PASSWORD)
    for email, role, name in DEMO_USERS:
        user = UserModel(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=email,
            hashed_password=password_hash,
            role=role.value,
            full_name=name,
        )
        session.add(user)
        admin_id = admin_id or user.id
    await session.flush()
    service = CaseCommandService(session, settings.audit_hmac_secret.get_secret_value().encode())

    step = _Runner(service, admin_id, org.id)
    await step(
        "open_case",
        {
            "title": "Спор по договору международной перевозки (демо)",
            "institution": "ICAC_MKAS",
            "seat": {"city": "Москва", "country": "RU"},
            "claim_amount": "12500000",
            "claim_currency": "RUB",
            "rules_edition": "Правила арбитража международных коммерческих споров МКАС",
            "party_countries": ["RU", "KZ"],
            "dispute_category": "commercial",
        },
    )
    await step("file_case", {"filing_ref": "DEMO-2026-0001"})
    await step("register_rfa", {"ref": "DEMO-REG-0001", "received_on": "2026-07-01"})
    await step(
        "add_party",
        {
            "party_id": "demo-claimant",
            "role": "claimant",
            "name": DEMO_ORG["name"],
            "inn": DEMO_ORG["inn"],
            "ogrn": DEMO_ORG["ogrn"],
        },
    )
    await step(
        "add_party",
        {
            "party_id": "demo-respondent",
            "role": "respondent",
            "name": "Demo Freight LLP (вымышленная организация)",
            "country": "KZ",
        },
    )
    arbitrators = [
        ("demo-arb-1", "claimant", "Арбитр А (демо)", True),
        ("demo-arb-2", "respondent", "Арбитр Б (демо)", False),
        ("demo-arb-3", "co_arbitrators", "Председатель В (демо)", True),
    ]
    for arb_id, side, name, law in arbitrators:
        await step(
            "nominate_arbitrator",
            {"arbitrator_id": arb_id, "side": side, "arbitrator_name": name, "law_degree": law},
        )
    await step(
        "constitute_tribunal",
        {"composition": "three", "chair_id": "demo-arb-3", "constituted_at": "2026-08-03"},
    )
    await step(
        "rule_on_jurisdiction",
        {"has_jurisdiction": True, "notified_on": "2026-08-20", "reasoning": "Демо"},
    )
    await step(
        "adopt_timetable",
        {
            "milestones": [
                {"code": "SoC", "due_at": "2026-09-01", "label": "Исковое заявление"},
                {"code": "SoD", "due_at": "2026-09-15", "label": "Отзыв на иск"},
            ],
            "po_ref": "ПП-1",
        },
    )
    await step("open_submission_round", {"round_code": "R1", "due_at": "2026-09-15"})
    await step("file_submission", {"round_code": "R1", "title": "Отзыв на иск (демо)"})
    await step(
        "issue_procedural_order",
        {"number": "ПП-2", "gist": "Слушание проводится в режиме видеоконференции."},
    )
    hearing = await step(
        "schedule_hearing", {"when": "2026-09-22T10:00:00+03:00", "format": "remote"}
    )
    await step("mark_hearing_held", {"hearing_id": hearing["events"][0]["payload"]["hearing_id"]})
    await step("start_deliberation", {})
    await step("draft_award", {"kind": "final", "operative_summary": "Демо"})
    await step("issue_award", {"kind": "final", "operative_summary": "Иск удовлетворить частично"})
    await step("receive_award", {"party_id": "demo-respondent", "received_on": "2026-10-01"})
    await step("receive_award", {"party_id": "demo-claimant", "received_on": "2026-10-02"})
    international_case = step.case_id

    adhoc = _Runner(service, admin_id, org.id)
    await adhoc(
        "open_case",
        {
            "title": "Внутренний спор ad hoc о поставке (демо)",
            "institution": "AD_HOC",
            "claim_amount": "3000000",
            "party_countries": ["RU"],
        },
    )
    await adhoc("file_case", {"filing_ref": "DEMO-ADHOC-1"})
    await adhoc("register_rfa", {"received_on": "2026-10-12"})
    await session.flush()
    return {
        "status": "seeded",
        "organization_id": org.id,
        "cases": [international_case, adhoc.case_id],
    }


async def main() -> None:
    settings = get_settings()
    configure_logging(json=False)
    engine = make_engine(settings.database_url, null_pool=True)
    try:
        async with make_sessionmaker(engine)() as session:
            result = await seed_demo(session, settings)
            await session.commit()
    finally:
        await engine.dispose()
    logger.info("seed.done", **result)


if __name__ == "__main__":
    asyncio.run(main())
