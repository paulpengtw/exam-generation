"""add failure_class to generation_question_states

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-04 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist the recognized provider failure class for each question."""
    with op.batch_alter_table("generation_question_states") as batch_op:
        batch_op.add_column(sa.Column("failure_class", sa.String(length=40), nullable=True))


def downgrade() -> None:
    """Drop the per-question provider failure class."""
    with op.batch_alter_table("generation_question_states") as batch_op:
        batch_op.drop_column("failure_class")
