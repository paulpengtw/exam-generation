"""ORM models for auth and generation logging."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

# queued / running / cancelled belong to the detached 生成執行 lifecycle
# (openspec detached-generation-runs D7). "started" remains for 人工審題修正 logs.
GenerationStatus = Enum(
    "started",
    "completed",
    "failed",
    "queued",
    "running",
    "cancelled",
    name="generation_status",
)
GenerationRecordStatus = Enum(
    "completed", "failed", "aborted", name="generation_record_status"
)


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    generation_logs: Mapped[list[GenerationLog]] = relationship(back_populates="user")


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GenerationLog(Base):
    __tablename__ = "generation_logs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "submission_key", name="uq_generation_logs_user_submission_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(GenerationStatus, nullable=False, default="started")
    question_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    figure_policy_trail_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_example_record_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 生成執行 claim state (detached-generation-runs D5/D7).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    claimed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    submission_key: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped[User] = relationship(back_populates="generation_logs")


class GenerationQuestionState(Base):
    """Persisted 處理狀態 of one manifest question of a 生成執行."""

    __tablename__ = "generation_question_states"
    __table_args__ = (
        UniqueConstraint(
            "generation_log_id",
            "question_id",
            name="uq_generation_question_states_log_question",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generation_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("generation_logs.id"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    processing: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")
    current_step: Mapped[str | None] = mapped_column(String(30), nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terminal_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("generation_records.id"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    generation_log_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("generation_logs.id"), nullable=True
    )
    parent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("generation_records.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(30), nullable=False)
    question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    annotations_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    question_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification_trail_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    figure_policy_trail_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_example_record_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    image_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        GenerationRecordStatus, nullable=False, default="completed"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class LLMExchange(Base):
    __tablename__ = "llm_exchanges"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    generation_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("generation_logs.id"),
        nullable=False,
        index=True,
    )
    exchange_order: Mapped[int] = mapped_column(Integer, nullable=False)
    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
