"""worker lease columns

Revision ID: 0003_worker_lease
Revises: 0002_run_lifecycle
Create Date: 2026-07-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_worker_lease"
down_revision: str | None = "0002_run_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_index(
        "ix_runs_state_lease_expires_at",
        "runs",
        ["state", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runs_state_lease_expires_at", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_id")
