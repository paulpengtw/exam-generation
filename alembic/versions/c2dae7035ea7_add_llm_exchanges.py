"""add_llm_exchanges

Revises: 3670c7404c79
Create Date: 2026-07-15 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2dae7035ea7"
down_revision: Union[str, Sequence[str], None] = "3670c7404c79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_log_id", sa.Uuid(), nullable=False),
        sa.Column("exchange_order", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["generation_log_id"], ["generation_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_exchanges_generation_log_id"),
        "llm_exchanges",
        ["generation_log_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_exchanges_generation_log_id"), table_name="llm_exchanges")
    op.drop_table("llm_exchanges")
