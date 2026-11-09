from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("inn", sa.String(12), nullable=False, unique=True),
        sa.Column("ogrn", sa.String(15), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organizations_inn", "organizations", ["inn"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])

    op.create_table(
        "domain_events",
        sa.Column("global_seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("organization_id", sa.String(36), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("aggregate_id", "version", name="uq_domain_events_agg_version"),
    )
    op.create_index("ix_domain_events_aggregate_id", "domain_events", ["aggregate_id"])
    op.create_index("ix_domain_events_org", "domain_events", ["organization_id"])
    op.create_index("ix_domain_events_type", "domain_events", ["event_type"])
    op.create_index("ix_domain_events_occurred", "domain_events", ["occurred_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
    )
    op.create_index("ix_outbox_unpublished", "outbox_events", ["published_at"])

    op.create_table(
        "case_status_projection",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("current_status", sa.String(64), nullable=False),
        sa.Column("institution", sa.String(32), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("claim_amount", sa.String(64), nullable=True),
        sa.Column("claim_currency", sa.String(8), nullable=True),
        sa.Column("seat_city", sa.String(128), nullable=True),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_case_status_org", "case_status_projection", ["organization_id"])
    op.create_index("ix_case_status_status", "case_status_projection", ["current_status"])

    op.create_table(
        "calendar_projection",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("entry_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("label", sa.String(512), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("case_id", "entry_key", name="uq_calendar_case_entry"),
    )
    op.create_index("ix_calendar_due", "calendar_projection", ["due_at"])
    op.create_index("ix_calendar_org", "calendar_projection", ["organization_id"])
    op.create_index("ix_calendar_case_id", "calendar_projection", ["case_id"])

    op.create_table(
        "tribunal_projection",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("composition", sa.String(32), nullable=True),
        sa.Column("chair_id", sa.String(36), nullable=True),
        sa.Column("members", postgresql.JSONB(), nullable=False),
        sa.Column("nominations", postgresql.JSONB(), nullable=False),
        sa.Column("constituted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("constituted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_tribunal_org", "tribunal_projection", ["organization_id"])

    op.create_table(
        "projection_checkpoints",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("last_global_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "procedural_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gist", sa.Text(), nullable=False),
        sa.Column("ai_summary_draft", sa.Text(), nullable=True),
        sa.Column(
            "requires_human_review", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("human_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_po_case_id", "procedural_orders", ["case_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_org", "audit_events", ["organization_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("procedural_orders")
    op.drop_table("projection_checkpoints")
    op.drop_table("tribunal_projection")
    op.drop_table("calendar_projection")
    op.drop_table("case_status_projection")
    op.drop_table("outbox_events")
    op.drop_table("domain_events")
    op.drop_table("users")
    op.drop_table("organizations")
