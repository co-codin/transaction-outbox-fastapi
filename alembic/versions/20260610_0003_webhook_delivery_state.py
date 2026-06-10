"""add webhook delivery state to payments

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_0003"
down_revision: str | None = "20260610_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("webhook_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("payments", sa.Column("webhook_last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "webhook_last_error")
    op.drop_column("payments", "webhook_sent_at")
