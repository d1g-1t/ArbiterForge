from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_event_store_relay"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.execute(
        "ALTER TABLE domain_events ADD COLUMN tx_id xid8 NOT NULL DEFAULT pg_current_xact_id()"
    )
    op.create_index("ix_domain_events_relay", "domain_events", ["tx_id", "global_seq"])
    op.execute(
        "ALTER TABLE projection_checkpoints ADD COLUMN last_tx_id xid8 NOT NULL DEFAULT '0'::xid8"
    )

    op.add_column("case_status_projection", sa.Column("regime", sa.String(16), nullable=True))

    op.add_column("procedural_orders", sa.Column("accepted_by", sa.String(36), nullable=True))
    op.add_column(
        "procedural_orders",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("audit_events", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE audit_events a SET seq = r.rn FROM ("
        "SELECT id, row_number() OVER (PARTITION BY organization_id ORDER BY created_at, id) AS rn "
        "FROM audit_events) r WHERE a.id = r.id"
    )
    op.alter_column("audit_events", "seq", nullable=False)
    op.create_unique_constraint("uq_audit_org_seq", "audit_events", ["organization_id", "seq"])


def downgrade() -> None:
    op.drop_constraint("uq_audit_org_seq", "audit_events", type_="unique")
    op.drop_column("audit_events", "seq")
    op.drop_column("procedural_orders", "accepted_at")
    op.drop_column("procedural_orders", "accepted_by")
    op.drop_column("case_status_projection", "regime")
    op.drop_column("projection_checkpoints", "last_tx_id")
    op.drop_index("ix_domain_events_relay", table_name="domain_events")
    op.drop_column("domain_events", "tx_id")
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
