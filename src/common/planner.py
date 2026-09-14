"""Generate candidate 核心問題 for a given topic using the planning model.

Subject-agnostic: callers supply the system/user prompt templates.
"""

from __future__ import annotations

import json
import logging
import re

from src.llm_client import LLMClient

logger = logging.getLogger(__name__)


class CandidateValidationError(ValueError):
    """Content-free diagnostics safe for the correction prompt and telemetry."""

    def __init__(
        self, stage: str, *, expected_count: int, actual_count: int = 0,
        received_count: int = 0, attempt: int = 1,
    ):
        self.stage = stage
        self.expected_count = expected_count
        self.actual_count = actual_count
        self.received_count = received_count
        self.attempt = attempt
        super().__init__(
            f"Planner validation failed: stage={stage} attempt={attempt} "
            f"expected_count={expected_count} actual_count={actual_count} "
            f"received_count={received_count}"
        )


def plan_core_questions(
    client: LLMClient,
    topic: str,
    *,
    system_prompt: str,
    user_prompt_template: str,
    n: int = 3,
    learning_stage: str = "第四學習階段",
    subject_filter: list[str] | None = None,
    grade: int | None = None,
) -> list[str]:
    """Call planning model, return n candidate 核心問題 for the given topic.

    `system_prompt` is formatted with {n, learning_stage}.
    `user_prompt_template` is formatted with {topic, n, subject_hint, grade_hint}.
    """
    subject_hint = f"\n科目偏好：{'、'.join(subject_filter)}" if subject_filter else ""
    grade_hint = f"\n目標年級：{grade}年級" if grade else ""

    system = system_prompt.format(n=n, learning_stage=learning_stage)
    user = user_prompt_template.format(
        topic=topic,
        n=n,
        subject_hint=subject_hint,
        grade_hint=grade_hint,
    )

    for attempt in range(2):
        try:
            raw = client.plan(system, user, purpose="plan_core_questions")
        except Exception:
            # Provider error messages can contain the request or response.
            # Preserve the failing boundary, never its raw message or chain.
            raise CandidateValidationError(
                "provider_call", expected_count=n, attempt=attempt + 1,
            ) from None
        try:
            return _parse_candidates(raw, n, attempt=attempt + 1)
        except CandidateValidationError as exc:
            if attempt == 0:
                user += (
                    f"\n上次回覆驗證失敗：階段={exc.stage}；"
                    f"實際可用={exc.actual_count}；預期={n}；收到項目={exc.received_count}。"
                    f"\n注意：請務必輸出剛好 {n} 個候選的 JSON 陣列。"
                    "每項必須是非空白且互不重複的核心問題字串；"
                    "不得用數字、物件、重複問題或佔位文字補足數量。只輸出完整陣列。"
                )
            else:
                raise


def _parse_candidates(raw: str, n: int, *, attempt: int = 1) -> list[str]:
    """Extract list[str] from LLM output; retry-tolerant."""
    if not isinstance(raw, str):
        raise CandidateValidationError("response_shape", expected_count=n, attempt=attempt)

    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        numbered = [re.fullmatch(r"\d+[.)、]\s*(.+)", line) for line in lines]
        if lines and all(numbered):
            result = [match.group(1).strip() for match in numbered]
        else:
            raise CandidateValidationError(
                "response_parse", expected_count=n, attempt=attempt,
            ) from None

    if not isinstance(result, list):
        raise CandidateValidationError("response_shape", expected_count=n, attempt=attempt)

    candidates = list(dict.fromkeys(
        item.strip() for item in result if isinstance(item, str) and item.strip()
    ))
    if len(candidates) < n:
        raise CandidateValidationError(
            "candidate_validation", expected_count=n, actual_count=len(candidates),
            received_count=len(result), attempt=attempt,
        )

    return candidates[:n]


def plan_context_angles(
    client: LLMClient,
    count: int,
    sampled_contexts: list[str],
    learning_content_pool: list[str],
    core_question: str | None = None,
    *,
    system_prompt: str,
    user_prompt_template: str,
    learning_stage: str = "第四學習階段",
) -> list:
    """Ask the planning model for `count` mutually-distinct 題材 briefs.

    Never raises. Per issue #128 Global Constraints, planning failures must
    never block generation: Opus errors, malformed JSON, out-of-set
    contexts, or any other per-entry invalidity degrade to a `None` in that
    slot rather than raising or duplicating a brief into another slot.

    Always returns a list of length exactly `count`, positionally aligned
    with the LLM's response order where possible (`result[i]` reflects the
    i-th returned entry, or `None` if that entry was missing/invalid).
    Slots are never filled by duplicating another slot's brief — a caller
    that needs `count` briefs and gets fewer valid ones must treat the
    `None` slots as "use a briefless prompt for this question".
    """
    from src.social_studies.schemas import CreativeBrief

    system = system_prompt.format(n=count, learning_stage=learning_stage)
    user = user_prompt_template.format(
        contexts="、".join(sampled_contexts),
        count=count,
        learning_content="、".join(learning_content_pool) or "（未指定）",
        core_question=core_question or "（未指定）",
    )

    try:
        raw = client.plan(system, user, purpose="plan_context_angles")
        entries = _parse_brief_candidates(raw)
    except Exception as exc:
        logger.warning(
            "plan_context_angles: planning call failed (%s); "
            "falling back to briefless prompts for all %d slot(s)",
            exc,
            count,
        )
        return [None] * count

    allowed = set(sampled_contexts)
    result: list[CreativeBrief | None] = []
    for i in range(count):
        entry = entries[i] if i < len(entries) else None
        if not isinstance(entry, dict):
            result.append(None)
            continue
        ctx = entry.get("selected_context")
        angle = entry.get("題材_angle") or entry.get("題材角度") or ""
        hooks = entry.get("framing_hooks") or []
        if not ctx or ctx not in allowed or not angle:
            result.append(None)
            continue
        if not isinstance(hooks, list):
            hooks = []
        try:
            result.append(CreativeBrief(
                selected_context=ctx,
                題材_angle=str(angle),
                framing_hooks=[str(h) for h in hooks if h],
            ))
        except Exception:
            result.append(None)

    if all(b is None for b in result):
        logger.warning(
            "plan_context_angles: no valid briefs among %d LLM entries "
            "for %d slot(s); falling back to briefless prompts",
            len(entries),
            count,
        )
    return result


def _parse_brief_candidates(raw: str) -> list:
    """Extract a JSON array of dicts from LLM output; retry-tolerant."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan_context_angles: could not parse JSON: {exc}") from exc

    if not isinstance(result, list):
        raise ValueError(
            f"plan_context_angles: expected JSON array, got {type(result).__name__}",
        )
    return result
