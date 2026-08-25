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
    embed_image_base64,
    make_combined_observer,
    make_queue_observer,
)
from server.generate.persistence import make_exchange_recorder, persist_generation_record
from server.generate.subjects import SUBJECTS
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)

_PATH_TOKEN = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]")
_INTERACTION_PATH = re.compile(r"^subquestions\[\d+\]\.interaction(?:\.|$)")
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
        if _INTERACTION_PATH.fullmatch(field_path) or _INTERACTION_PATH.match(field_path):
            continue
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


def _stage_event(
    status: str,
    *,
    agent: str = "corrector",
    stage: str = "modification",
    retry: int | None = None,
) -> dict[str, Any]:
    step = {
        "modification": "修改",
        "verify": "驗證",
        "correct": "修正",
    }.get(stage, stage)
    data: dict[str, Any] = {
        "type": "stage",
        "agent": agent,
        "stage": stage,
        "step": step,
        "status": status,
        "ts": time.time(),
    }
    if retry is not None:
        data["retry"] = retry
    return {
        "event": SSEEventName.STAGE,
        "data": data,
    }


def _pipeline_event(
    status: str,
    *,
    stage: str = "modification",
    direct: bool = False,
) -> dict[str, Any]:
    del direct
    return {
        "event": SSEEventName.PIPELINE,
        "data": {
            "event_name": f"{stage}_{status}",
            "stage": stage,
            "step": {
                "modification": "修改",
                "verification": "驗證",
                "correction": "修正",
            }.get(stage, stage),
            "status": "start" if status == "start" else "end",
            "ts": time.time(),
        },
    }


async def _flush_observer_queue(queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    """Yield observer events scheduled by a background LLM call in order."""
    await asyncio.sleep(0)
    events: list[dict[str, Any]] = []
    while not queue.empty():
        events.append(await queue.get())
    return events


def _verification_payload(verification: Any) -> dict[str, Any]:
    if hasattr(verification, "model_dump"):
        return verification.model_dump(mode="json", exclude_none=False)
    if isinstance(verification, Mapping):
        return copy.deepcopy(dict(verification))
    return copy.deepcopy(vars(verification))


def _payload_has_image(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("圖片") or payload.get("image_base64"))


def _image_source_was_edited(
    base_question: Mapping[str, Any], annotations: list[dict[str, Any]]
) -> bool:
    """Return whether an existing image's text input was selected for editing."""
    top_level_image = _payload_has_image(base_question)
    subquestions = base_question.get("subquestions")
    subquestion_images = {
        index
        for index, subquestion in enumerate(subquestions or [])
        if isinstance(subquestion, Mapping) and _payload_has_image(subquestion)
    }
    if not top_level_image and not subquestion_images:
        return False

    for annotation in annotations:
        segments = annotation.get("segments") or annotation.get("圈選") or []
        for segment in segments:
            field_path = segment.get("field_path")
            if not isinstance(field_path, str):
                continue
            try:
                tokens = _path_tokens(field_path)
            except KeyError:
                continue
            if tokens and tokens[0] == "文本":
                return True
            if top_level_image and tokens and tokens[0] == "題目":
                return True
            if (
                len(tokens) >= 3
                and tokens[0] == "subquestions"
                and isinstance(tokens[1], int)
                and tokens[1] in subquestion_images
                and tokens[2] == "題目"
            ):
                return True
    return False


def _chart_image_path(payload: Mapping[str, Any], config: ServerConfig) -> str | None:
    image_name = payload.get("圖片")
    if not image_name:
        for subquestion in payload.get("subquestions", []) or []:
            if isinstance(subquestion, Mapping) and subquestion.get("圖片"):
                image_name = subquestion["圖片"]
                break
    if not isinstance(image_name, str):
        return None
    image_path = config.output_dir / image_name
    return str(image_path) if image_path.exists() else None


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
    figure_policy_trail_json: list[dict[str, Any]] | None = None,
    client_factory: Callable[..., Any] | None = None,
    subjects: Mapping[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run modification, full verification, and bounded correction rounds."""
    registry = subjects if subjects is not None else SUBJECTS
    spec = registry[subject]
    corrector = spec.correct_question
    if corrector is None:
        raise RuntimeError(f"Subject {subject!r} has no shared corrector")
    verifier = spec.verify_question
    if verifier is None:
        raise RuntimeError(f"Subject {subject!r} has no shared verifier")

    current_payload = copy.deepcopy(base_question)
    image_source_was_edited = _image_source_was_edited(base_question, annotations)
    question = spec.exam_question_cls.model_validate(current_payload)
    annotation_text = format_modification_annotations(annotations)
    modification_context = SimpleNamespace(
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
            modification_context,
            annotations=annotation_text,
            editable_paths=editable_paths,
        )
        for event in await _flush_observer_queue(queue):
            yield event

        candidate = json.loads(corrected.model_dump_json(exclude_none=False))
        current_payload = _merge_scoped(base_question, candidate, editable_paths)
        question = spec.exam_question_cls.model_validate(current_payload)
        yield _stage_event("end")
        yield _pipeline_event("end")

        max_retries = max(0, int(config.max_retries))
        retry = 0
        while True:
            yield _pipeline_event("start", stage="verification")
            yield _stage_event("start", agent="verifier", stage="verify", retry=retry or None)
            verification = await asyncio.to_thread(
                verifier,
                client,
                question,
                chart_image_path=_chart_image_path(current_payload, config),
                curriculum_context=None,
            )
            for event in await _flush_observer_queue(queue):
                yield event
            yield _stage_event("end", agent="verifier", stage="verify", retry=retry or None)
            yield _pipeline_event("end", stage="verification")

            if verification.passed or retry >= max_retries:
                break

            retry += 1
            yield _pipeline_event("start", stage="correction")
            yield _stage_event("start", agent="corrector", stage="correct", retry=retry)
            correction = await asyncio.to_thread(
                corrector,
                client,
                question,
                verification,
                annotations=annotation_text,
                editable_paths=editable_paths,
            )
            for event in await _flush_observer_queue(queue):
                yield event
            correction_candidate = json.loads(
                correction.model_dump_json(exclude_none=False)
            )
            # Use the last scoped attempt as the base.  This prevents an
            # irreconcilable verifier result from reverting the user's 修改 call.
            current_payload = _merge_scoped(
                current_payload, correction_candidate, editable_paths
            )
            question = spec.exam_question_cls.model_validate(current_payload)
            yield _stage_event("end", agent="corrector", stage="correct", retry=retry)
            yield _pipeline_event("end", stage="correction")

        verification_data = _verification_payload(verification)
        final_question = embed_image_base64(copy.deepcopy(current_payload), config)
        if image_source_was_edited:
            final_question["image_stale"] = True
        final_question["verification"] = verification_data
        ripple_report = sorted(
            field_path
            for field_path in dependent_paths
            if _read_path(base_question, field_path)
            != _read_path(final_question, field_path)
        )
        result_payload: dict[str, Any] = {
            "question": final_question,
            "ripple_report": ripple_report,
            "verified": bool(verification.passed),
            "verification": verification_data,
            "failure_details": (
                verification_data.get("details", "")
                if not verification.passed
                else None
            ),
        }
        params_json = {
            "kind": "manual_modification",
            "record_id": str(record_id),
            "annotations": annotations,
            "editable_paths": sorted(editable_paths),
            "dependent_paths": sorted(dependent_paths),
        }
        child_record_id = await persist_generation_record(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            params=params_json,
            payload=final_question,
            session_factory=session_factory,
            parent_record_id=record_id,
            annotations_json={"annotations": annotations},
            figure_policy_trail_json=figure_policy_trail_json,
        )
        result_payload["record_id"] = (
            str(child_record_id) if child_record_id is not None else None
        )
        yield {"event": SSEEventName.RESULT, "data": result_payload}
        # Keep the terminal event self-contained for clients that treat `done`
        # as the final snapshot event, while retaining the generate-route result
        # convention above.
        yield {"event": SSEEventName.DONE, "data": result_payload}
    except Exception:
        logger.exception("manual modification run failed")
        raise
