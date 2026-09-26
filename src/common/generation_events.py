"""Immutable generation identity types shared by CLI, core, and server.

Generation workers run in different threads, and provider callbacks can arrive
after a superseding attempt has started.  Ownership therefore travels with
every call instead of being inferred from a thread, an agent name, or event
order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Union

# These keys never count as question content.  The snapshot ledger strips them
# at any depth before signing (it hashes decoded image_base64 bytes separately)
# and the generation core's post-draft change check strips the same set.
CONTENT_SIGNATURE_EXCLUDED_KEYS: frozenset[str] = frozenset(
    [
        "verification",
        "verification_trail",
        "figure_policy_trail",
        "reference_example_record",
        "image_base64",
        "metadata",
        "review",
        "progress",
        "export",
        "_export",
    ]
)


@dataclass(frozen=True)
class RunContext:
    run_id: str


@dataclass(frozen=True)
class QuestionContext:
    run_id: str
    question_id: str
    index: int


@dataclass(frozen=True, slots=True)
class OperationScope:
    """Immutable identity for one concrete application-level work attempt."""

    run_id: str
    operation_id: str
    kind: str
    question_id: str | None = None
    index: int | None = None
    subquestion_index: int | None = None
    supersedes_operation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        if not self.operation_id:
            raise ValueError("operation_id must not be empty")
        if not self.kind:
            raise ValueError("operation kind must not be empty")
        if self.supersedes_operation_id == self.operation_id:
            raise ValueError("an operation cannot supersede itself")


@dataclass(frozen=True, slots=True)
class CallScope:
    """Immutable identity for one observable provider dispatch."""

    run_id: str
    operation_id: str
    call_id: str
    retry_of_call_id: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.operation_id or not self.call_id:
            raise ValueError("run, operation, and call ids must not be empty")
        if self.retry_of_call_id == self.call_id:
            raise ValueError("a call cannot retry itself")


# Compatibility vocabulary for boundary adapters that use context-oriented
# names.  The values remain the same immutable objects.
OperationContext = OperationScope
CallContext = CallScope
GenerationScope = Union[QuestionContext, OperationScope]


def new_run_id() -> str:
    """Return a new UUID4 as a hex string (no dashes)."""
    return uuid.uuid4().hex


def new_operation_scope(
    context: QuestionContext | RunContext | OperationScope,
    *,
    kind: str,
    subquestion_index: int | None = None,
    supersedes_operation_id: str | None = None,
) -> OperationScope:
    """Create a fresh operation owned by *context*.

    The identifier is opaque outside this module.  The run prefix is useful in
    logs and makes accidental cross-run pairing obvious, but consumers must not
    parse it to recover question or slot ownership.
    """
    if isinstance(context, OperationScope):
        run_id = context.run_id
        question_id = context.question_id
        index = context.index
    elif isinstance(context, QuestionContext):
        run_id = context.run_id
        question_id = context.question_id
        index = context.index
    else:
        run_id = context.run_id
        question_id = None
        index = None
    return OperationScope(
        run_id=run_id,
        operation_id=f"{run_id}:operation:{uuid.uuid4().hex}",
        kind=kind,
        question_id=question_id,
        index=index,
        subquestion_index=subquestion_index,
        supersedes_operation_id=supersedes_operation_id,
    )


def new_call_scope(
    operation: OperationScope,
    *,
    retry_of_call_id: str | None = None,
) -> CallScope:
    """Create the one call identity for an observable provider dispatch."""
    return CallScope(
        run_id=operation.run_id,
        operation_id=operation.operation_id,
        call_id=f"{operation.run_id}:call:{uuid.uuid4().hex}",
        retry_of_call_id=retry_of_call_id,
    )


def allocate_manifest(
    subject_prefix: str,
    run_id: str,
    count: int,
) -> tuple[QuestionContext, ...]:
    """Allocate a fixed manifest of QuestionContext for a batch.

    question_id format: f'{subject_prefix}{run_id}_{index+1:03d}'
    where index is 0-based and the ordinal is zero-padded to 3 digits minimum.
    """
    return tuple(
        QuestionContext(
            run_id=run_id,
            question_id=f"{subject_prefix}{run_id}_{i + 1:03d}",
            index=i,
        )
        for i in range(count)
    )
