"""add webhook lock and outbox cleanup index

Revision ID: 20260610_0004
Revises: 20260610_0003
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_0004"
down_revision: str | None = "20260610_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("webhook_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_status_published_at",
        "outbox",
        ["status", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_published_at", table_name="outbox")
    op.drop_column("payments", "webhook_locked_until")
