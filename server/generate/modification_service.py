"""Execution service for a 人工審題修正 run.

The service deliberately has one LLM boundary: the subject's existing corrector
receives the complete base question and the formatted 圈選/修改指示 batch.  The
candidate is then scoped against the raw base JSON before it is persisted.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from types import SimpleNamespace
from typing import Any

from server.config import ServerConfig
from server.generate.marshalling import (
    SSEEventName,
    make_combined_observer,
    make_queue_observer,
)
from server.generate.persistence import make_exchange_recorder, persist_generation_record
from server.generate.subjects import SUBJECTS
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)

_PATH_TOKEN = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]")
_MISSING = object()


def _path_tokens(field_path: str) -> list[str | int]:
    tokens: list[str | int] = []
    consumed = 0
    for match in _PATH_TOKEN.finditer(field_path):
        consumed = match.end()
        key, index = match.groups()
        tokens.append(key if key is not None else int(index))
    if not tokens or consumed != len(field_path):
        raise KeyError(field_path)
    return tokens


def _read_path(payload: Mapping[str, Any], field_path: str) -> object:
    current: object = payload
    try:
        tokens = _path_tokens(field_path)
        for token in tokens:
            if isinstance(token, str):
                if not isinstance(current, dict) or token not in current:
                    return _MISSING
                current = current[token]
            else:
                if not isinstance(current, list) or token >= len(current):
                    return _MISSING
                current = current[token]
    except (KeyError, TypeError):
        return _MISSING
    return current


def _write_path(payload: dict[str, Any], field_path: str, value: object) -> None:
    tokens = _path_tokens(field_path)
    if not tokens:
        return
    current: object = payload
    for token in tokens[:-1]:
        if isinstance(token, str):
            if not isinstance(current, dict) or token not in current:
                return
            current = current[token]
        else:
            if not isinstance(current, list) or token >= len(current):
                return
            current = current[token]
    last = tokens[-1]
    if isinstance(last, str):
        if isinstance(current, dict):
            current[last] = copy.deepcopy(value)
    elif isinstance(current, list) and last < len(current):
        current[last] = copy.deepcopy(value)


def _merge_scoped(
    base: dict[str, Any], candidate: Mapping[str, Any], editable_paths: set[str]
) -> dict[str, Any]:
    """Copy only explicitly editable paths from a whole-question candidate."""
    merged = copy.deepcopy(base)
    for field_path in sorted(editable_paths):
        value = _read_path(candidate, field_path)
        if value is not _MISSING:
            _write_path(merged, field_path, value)
    return merged


def format_modification_annotations(annotations: list[dict[str, Any]]) -> str:
    """Render structured annotations as requested edits for the shared corrector."""
    blocks: list[str] = []
    for index, annotation in enumerate(annotations, start=1):
        instruction = (
            annotation.get("修改指示")
            or annotation.get("modification_instruction")
            or annotation.get("instruction")
            or ""
        )
        segments = annotation.get("segments") or annotation.get("圈選") or []
        selected = "; ".join(
            f"{segment.get('field_path')}[{segment.get('start')}:{segment.get('end')}]"
            f"：「{segment.get('quoted_text', '')}」"
            for segment in segments
        )
        blocks.append(
            f"圈選 {index}：{selected}\n"
            f"修改指示：{instruction}"
        )
    return "\n\n".join(blocks)


def _stage_event(status: str) -> dict[str, Any]:
    return {
        "event": SSEEventName.STAGE,
        "data": {
            "type": "stage",
            "agent": "corrector",
            "stage": "modification",
            "status": status,
            "ts": time.time(),
        },
    }


def _pipeline_event(status: str, *, direct: bool = False) -> dict[str, Any]:
    del direct
    return {
        "event": SSEEventName.PIPELINE,
        "data": {
            "event_name": f"modification_{status}",
            "stage": "modification",
            "status": "start" if status == "start" else "end",
            "ts": time.time(),
        },
    }


async def modification_question_stream(
    *,
    base_question: dict[str, Any],
    subject: str,
    record_id: uuid.UUID,
    generation_log_id: uuid.UUID,
    annotations: list[dict[str, Any]],
    editable_paths: set[str],
    dependent_paths: set[str],
    config: ServerConfig,
    user_id: uuid.UUID,
    session_factory: Any,
    client_factory: Callable[..., Any] | None = None,
    subjects: Mapping[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one modification corrector call and stream its lifecycle."""
    registry = subjects if subjects is not None else SUBJECTS
    spec = registry[subject]
    corrector = spec.correct_question
    if corrector is None:
        raise RuntimeError(f"Subject {subject!r} has no shared corrector")

    question = spec.exam_question_cls.model_validate(base_question)
    annotation_text = format_modification_annotations(annotations)
    verification = SimpleNamespace(
        passed=False,
        answer_match=False,
        details="人工審題修正：依據使用者的圈選與修改指示執行一次修改。",
        my_answer="",
        provided_answer="",
        chart_verification=None,
    )
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    recorder = make_exchange_recorder(
        generation_log_id=generation_log_id,
        retention_days=config.llm_exchange_retention_days,
        loop=loop,
        session_factory=session_factory,
        next_order=itertools.count(1).__next__,
    )
    factory = client_factory or LLMClient
    client = factory(config)
    client.set_observer(
        make_combined_observer(make_queue_observer(loop, queue), recorder)
    )

    yield {"event": SSEEventName.STARTED, "data": ""}
    yield _pipeline_event("start")
    yield _stage_event("start")

    try:
        corrected = await asyncio.to_thread(
            corrector,
            client,
            question,
            verification,
            annotations=annotation_text,
            editable_paths=editable_paths,
        )
        # Observer callbacks schedule SSE events on the event loop.  Let those
        # callbacks run before publishing the stage completion and final result.
        await asyncio.sleep(0)
        while not queue.empty():
            yield await queue.get()

        candidate = json.loads(corrected.model_dump_json(exclude_none=False))
        modified_question = _merge_scoped(base_question, candidate, editable_paths)
        ripple_report = sorted(
            field_path
            for field_path in dependent_paths
            if _read_path(base_question, field_path)
            != _read_path(modified_question, field_path)
        )
        result_payload = {
            "question": modified_question,
            "ripple_report": ripple_report,
        }
        params_json = {
            "kind": "manual_modification",
            "record_id": str(record_id),
            "annotations": annotations,
            "editable_paths": sorted(editable_paths),
            "dependent_paths": sorted(dependent_paths),
        }
        await persist_generation_record(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            params=params_json,
            payload=modified_question,
            session_factory=session_factory,
            parent_record_id=record_id,
            annotations_json={"annotations": annotations},
        )
        yield _stage_event("end")
        yield _pipeline_event("end")
        yield {"event": SSEEventName.RESULT, "data": result_payload}
        # Keep the terminal event self-contained for clients that treat `done`
        # as the final snapshot event, while retaining the generate-route result
        # convention above.
        yield {"event": SSEEventName.DONE, "data": result_payload}
    except Exception:
        logger.exception("manual modification run failed")
        raise
