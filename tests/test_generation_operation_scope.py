from __future__ import annotations

import dataclasses

import pytest

from src.common.generation_events import (
    QuestionContext,
    new_call_scope,
    new_operation_scope,
)


def test_operation_and_call_scopes_are_run_unique_and_immutable() -> None:
    question = QuestionContext(run_id="RUN", question_id="q-1", index=0)

    operation = new_operation_scope(
        question,
        kind="subquestion",
        subquestion_index=2,
    )
    retry_operation = new_operation_scope(
        question,
        kind="subquestion",
        subquestion_index=2,
        supersedes_operation_id=operation.operation_id,
    )
    first_call = new_call_scope(operation)
    retry_call = new_call_scope(retry_operation, retry_of_call_id=first_call.call_id)

    assert operation.run_id == retry_operation.run_id == first_call.run_id == "RUN"
    assert operation.operation_id != retry_operation.operation_id
    assert operation.operation_id.startswith("RUN:")
    assert first_call.call_id != retry_call.call_id
    assert first_call.call_id.startswith("RUN:")
    assert retry_call.retry_of_call_id == first_call.call_id
    assert retry_operation.supersedes_operation_id == operation.operation_id
    with pytest.raises(dataclasses.FrozenInstanceError):
        operation.operation_id = "mutated"  # type: ignore[misc]

