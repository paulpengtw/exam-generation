"""add generation record parent and annotations fields

Revision ID: f4b1e3c7a901
Revises: 8d8c3b2fd2a1
Create Date: 2026-08-23 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f4b1e3c7a901"
down_revision: Union[str, Sequence[str], None] = "8d8c3b2fd2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PARENT_RECORD_FK = "fk_generation_records_parent_record_id"


def upgrade() -> None:
    """Store the source record and annotations for corrected generations."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.add_column(sa.Column("parent_record_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("annotations_json", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            _PARENT_RECORD_FK,
            "generation_records",
            ["parent_record_id"],
            ["id"],
        )


def downgrade() -> None:
    """Remove correction provenance fields while preserving generation records."""
    with op.batch_alter_table("generation_records") as batch_op:
        batch_op.drop_constraint(_PARENT_RECORD_FK, type_="foreignkey")
        batch_op.drop_column("annotations_json")
        batch_op.drop_column("parent_record_id")
