"""baseline_channels table

Revision ID: 0004_baseline_channels
Revises: 0003_worker_lease
Create Date: 2026-07-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_baseline_channels"
down_revision: str | None = "0003_worker_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "baseline_channels",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("channel", sa.String(length=200), nullable=False),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("previous_run_id", sa.String(length=64), nullable=True),
        sa.Column(
            "promoted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "channel", name="uq_baseline_project_channel"),
    )


def downgrade() -> None:
    op.drop_table("baseline_channels")
