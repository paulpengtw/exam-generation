"""add cancelled to generation_status

Revision ID: e3c2e6f4d9b5
Revises: e2b1d5e3c8a4
Create Date: 2026-09-29 00:00:00.000000

Postgres cannot use a new enum value in the transaction that added it, so each
生成執行 status value gets its own migration run in an autocommit block
(detached-generation-runs D7). SQLite stores the enum as plain VARCHAR without a
CHECK constraint, so there is nothing to alter there.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e3c2e6f4d9b5"
down_revision: Union[str, Sequence[str], None] = "e2b1d5e3c8a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'cancelled' to the native generation_status enum."""
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE generation_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    """Postgres cannot drop an enum value; the rollback path leaves it unused."""
