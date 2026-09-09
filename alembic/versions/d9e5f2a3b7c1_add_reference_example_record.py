"""add reference example record persistence columns

Revision ID: d9e5f2a3b7c1
Revises: c8d4f1a2b6e0
Create Date: 2026-09-10 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d9e5f2a3b7c1"
down_revision: Union[str, Sequence[str], None] = "c8d4f1a2b6e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store the completed reference example record and its incremental generation-log staging copy."""
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.add_column(sa.Column("reference_example_record_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.add_column(sa.Column("reference_example_record_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove reference example record persistence columns."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_column("reference_example_record_json")

    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.drop_column("reference_example_record_json")
