"""unique constraint on (generation_log_id, question_id) in generation_records

Revision ID: e3f6b2c1a4d8
Revises: d9e5f2a3b7c1
Create Date: 2026-09-30 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e3f6b2c1a4d8"
down_revision: Union[str, Sequence[str], None] = "d9e5f2a3b7c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on (generation_log_id, question_id) in generation_records.

    NULL generation_log_id values remain distinct under SQL NULL semantics, so
    rows without a generation log never conflict with each other.  The constraint only
    fires when both columns are non-NULL, preventing duplicate saves of the same
    question within the same run (issue #907).

    The production duplicate pre-check (2026-09-29) found 0 duplicate pairs, so
    no deduplication step precedes this migration (see DEPLOYMENT.md § "Production
    facts before detached generation runs").
    """
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.create_unique_constraint(
            "uq_generation_records_log_question",
            ["generation_log_id", "question_id"],
        )


def downgrade() -> None:
    """Remove the unique constraint from generation_records."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_constraint(
            "uq_generation_records_log_question", type_="unique"
        )
