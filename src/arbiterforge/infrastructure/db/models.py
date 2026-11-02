from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Xid8(UserDefinedType[int]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "XID8"


ischema_names["xid8"] = Xid8


class Base(DeclarativeBase):
    pass


class OrganizationModel(Base):
    __tablename__ = "organizations"
    __table_args__ = (Index("ix_organizations_inn", "inn"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inn: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    ogrn: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    users: Mapped[list[UserModel]] = relationship(back_populates="organization", lazy="raise")


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped[OrganizationModel] = relationship(back_populates="users", lazy="raise")


class DomainEventModel(Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "version", name="uq_domain_events_agg_version"),
        Index("ix_domain_events_org", "organization_id"),
        Index("ix_domain_events_type", "event_type"),
        Index("ix_domain_events_occurred", "occurred_at"),
        Index("ix_domain_events_relay", "tx_id", "global_seq"),
    )

    global_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    tx_id: Mapped[int] = mapped_column(
        Xid8(), nullable=False, server_default=text("pg_current_xact_id()")
    )


class CaseStatusProjectionModel(Base):
    __tablename__ = "case_status_projection"
    __table_args__ = (
        Index("ix_case_status_org", "organization_id"),
        Index("ix_case_status_status", "current_status"),
    )

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    current_status: Mapped[str] = mapped_column(String(64), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_amount: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    seat_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class CalendarProjectionModel(Base):
    __tablename__ = "calendar_projection"
    __table_args__ = (
        UniqueConstraint("case_id", "entry_key", name="uq_calendar_case_entry"),
        Index("ix_calendar_due", "due_at"),
        Index("ix_calendar_org", "organization_id"),
        Index("ix_calendar_case_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    entry_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TribunalProjectionModel(Base):
    __tablename__ = "tribunal_projection"
    __table_args__ = (Index("ix_tribunal_org", "organization_id"),)

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    composition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chair_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    members: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    nominations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    constituted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    constituted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")


class ProjectionCheckpointModel(Base):
    __tablename__ = "projection_checkpoints"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_global_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_tx_id: Mapped[int] = mapped_column(
        Xid8(), nullable=False, server_default=text("'0'::xid8")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProceduralOrderModel(Base):
    __tablename__ = "procedural_orders"
    __table_args__ = (Index("ix_po_case_id", "case_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gist: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_summary_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    human_accepted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    accepted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "seq", name="uq_audit_org_seq"),
        Index("ix_audit_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
