"""allow failed status for outbox events

Revision ID: 20260610_0002
Revises: 20260610_0001
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260610_0002"
down_revision: str | None = "20260610_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_outbox_status", "outbox", type_="check")
    op.create_check_constraint(
        "ck_outbox_status",
        "outbox",
        "status in ('pending', 'published', 'failed')",
    )


def downgrade() -> None:
    op.execute("UPDATE outbox SET status = 'pending' WHERE status = 'failed'")
    op.drop_constraint("ck_outbox_status", "outbox", type_="check")
    op.create_check_constraint(
        "ck_outbox_status",
        "outbox",
        "status in ('pending', 'published')",
    )
