"""run lifecycle and idempotency

Revision ID: 0002_run_lifecycle
Revises: 0001_initial
Create Date: 2026-07-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from model_regression_detection.persistence.models import PortableJson

revision: str = "0002_run_lifecycle"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column("snapshot", PortableJson(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("state", sa.String(length=32), nullable=False, server_default="completed")
        )
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("execution_status", existing_type=sa.String(length=32), nullable=True)
        batch_op.alter_column("gate_outcome", existing_type=sa.String(length=32), nullable=True)
        batch_op.alter_column("total_cases", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("metrics", existing_type=PortableJson(), nullable=True)

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_idempotency_project_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.alter_column("metrics", existing_type=PortableJson(), nullable=False)
        batch_op.alter_column("total_cases", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("gate_outcome", existing_type=sa.String(length=32), nullable=False)
        batch_op.alter_column(
            "execution_status", existing_type=sa.String(length=32), nullable=False
        )
        batch_op.drop_column("completed_at")
        batch_op.drop_column("state")
        batch_op.drop_column("snapshot")
