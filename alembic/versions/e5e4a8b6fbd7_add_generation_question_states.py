"""add generation_question_states

Revision ID: e5e4a8b6fbd7
Revises: e4d3f7a5eac6
Create Date: 2026-09-29 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e5e4a8b6fbd7"
down_revision: Union[str, Sequence[str], None] = "e4d3f7a5eac6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist each manifest question's 處理狀態, 生成步驟 and 終止原因."""
    op.create_table(
        "generation_question_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_log_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(length=100), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("processing", sa.String(length=20), nullable=False),
        sa.Column("current_step", sa.String(length=30), nullable=True),
        sa.Column("termination_reason", sa.String(length=20), nullable=True),
        sa.Column("terminal_json", sa.JSON(), nullable=True),
        sa.Column("generation_record_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["generation_log_id"], ["generation_logs.id"]),
        sa.ForeignKeyConstraint(["generation_record_id"], ["generation_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_log_id",
            "question_id",
            name="uq_generation_question_states_log_question",
        ),
    )
    op.create_index(
        "ix_generation_question_states_generation_log_id",
        "generation_question_states",
        ["generation_log_id"],
    )


def downgrade() -> None:
    """Drop the per-question state table."""
    op.drop_index(
        "ix_generation_question_states_generation_log_id",
        table_name="generation_question_states",
    )
    op.drop_table("generation_question_states")
