"""create payments and outbox tables

Revision ID: 20260610_0001
Revises:
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260610_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("webhook_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("currency in ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        sa.CheckConstraint(
            "status in ('pending', 'succeeded', 'failed')",
            name="ck_payments_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)

    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'published')",
            name="ck_outbox_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"], unique=False)
    op.create_index("ix_outbox_status_created_at", "outbox", ["status", "created_at"], unique=False)
    op.create_index(
        "ix_outbox_status_published_at",
        "outbox",
        ["status", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_published_at", table_name="outbox")
    op.drop_index("ix_outbox_status_created_at", table_name="outbox")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_table("payments")
