"""add generation record tombstone fields

Revision ID: 8d8c3b2fd2a1
Revises: 3a3b61d0b77f
Create Date: 2026-08-23 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8d8c3b2fd2a1"
down_revision: Union[str, Sequence[str], None] = "3a3b61d0b77f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GENERATION_RECORD_STATUS = sa.Enum(
    "completed", "failed", "aborted", name="generation_record_status"
)


def upgrade() -> None:
    """Add explicit record status/error fields and allow failed payloads to be null."""
    _GENERATION_RECORD_STATUS.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.add_column(sa.Column("status", _GENERATION_RECORD_STATUS, nullable=True))
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch_op.alter_column(
            "question_json",
            existing_type=sa.JSON(),
            existing_nullable=False,
            nullable=True,
        )

    op.execute(
        sa.text(
            "UPDATE generation_records SET status = 'completed' "
            "WHERE status IS NULL"
        )
    )

    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_GENERATION_RECORD_STATUS,
            existing_nullable=True,
            nullable=False,
        )


def downgrade() -> None:
    """Restore the pre-tombstone schema.

    The old schema cannot represent a failed/aborted record because its
    question payload is required. Those feature-only rows therefore follow
    the pre-feature behavior and are removed during downgrade; completed
    records remain intact.
    """
    op.execute(
        sa.text(
            "DELETE FROM generation_records "
            "WHERE status IN ('failed', 'aborted')"
        )
    )

    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_column("error")
        batch_op.drop_column("status")
        batch_op.alter_column(
            "question_json",
            existing_type=sa.JSON(),
            existing_nullable=True,
            nullable=False,
        )

    _GENERATION_RECORD_STATUS.drop(op.get_bind(), checkfirst=True)
