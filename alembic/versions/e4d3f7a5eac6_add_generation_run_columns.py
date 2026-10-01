"""add 生成執行 claim columns to generation_logs

Revision ID: e4d3f7a5eac6
Revises: e3c2e6f4d9b5
Create Date: 2026-09-29 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e4d3f7a5eac6"
down_revision: Union[str, Sequence[str], None] = "e3c2e6f4d9b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SUBMISSION_KEY_UNIQUE = "uq_generation_logs_user_submission_key"


def upgrade() -> None:
    """Add heartbeat, attempt, claim, cancel and submission-key columns."""
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.add_column(
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("claimed_by", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column(
                "cancel_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("submission_key", sa.String(length=100), nullable=True)
        )
        batch_op.create_unique_constraint(
            _SUBMISSION_KEY_UNIQUE, ["user_id", "submission_key"]
        )


def downgrade() -> None:
    """Drop the claim columns; existing generation logs are otherwise untouched."""
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.drop_constraint(_SUBMISSION_KEY_UNIQUE, type_="unique")
        batch_op.drop_column("submission_key")
        batch_op.drop_column("cancel_requested")
        batch_op.drop_column("claimed_by")
        batch_op.drop_column("attempts")
        batch_op.drop_column("heartbeat_at")
