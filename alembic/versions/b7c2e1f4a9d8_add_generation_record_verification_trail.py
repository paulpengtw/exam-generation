"""add generation record verification trail

Revision ID: b7c2e1f4a9d8
Revises: f4b1e3c7a901
Create Date: 2026-08-24 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7c2e1f4a9d8"
down_revision: Union[str, Sequence[str], None] = "f4b1e3c7a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store typed verification verdict history beside each question."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.add_column(sa.Column("verification_trail_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove persisted verification verdict history."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_column("verification_trail_json")
