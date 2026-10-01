"""add failure_class column to generation_logs

Revision ID: f1a2b3c4d5e6
Revises: 8aa86c08f8eb
Create Date: 2026-10-01 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "8aa86c08f8eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable failure_class column to generation_logs.

    Records the LLM provider error taxonomy code when a generation run fails.
    Values are one of the ten stable codes from classify_provider_error:
    auth_config | quota_billing_exhausted | rate_limited | overloaded |
    timeout | connection | context_length | content_filtered |
    malformed_response | unknown

    Existing failed runs have NULL (unknown at migration time).
    """
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.add_column(
            sa.Column("failure_class", sa.String(length=40), nullable=True)
        )


def downgrade() -> None:
    """Drop the failure_class column."""
    with op.batch_alter_table("generation_logs") as batch_op:
        batch_op.drop_column("failure_class")
