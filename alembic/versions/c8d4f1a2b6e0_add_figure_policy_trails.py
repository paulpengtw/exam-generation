"""add figure policy trail persistence columns

Revision ID: c8d4f1a2b6e0
Revises: b7c2e1f4a9d8
Create Date: 2026-08-25 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c8d4f1a2b6e0"
down_revision: Union[str, Sequence[str], None] = "b7c2e1f4a9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store the completed trail and its incremental generation-log staging copy."""
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.add_column(sa.Column("figure_policy_trail_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.add_column(sa.Column("figure_policy_trail_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove figure policy trail persistence columns."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_column("figure_policy_trail_json")

    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.drop_column("figure_policy_trail_json")
