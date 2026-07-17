"""Generate candidate 核心問題 for a given topic using the planning model.

Subject-agnostic: callers supply the system/user prompt templates.
"""

from __future__ import annotations

import json
import re

from src.llm_client import LLMClient


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
        raw = client.plan(system, user, purpose="plan_core_questions")
        try:
            return _parse_candidates(raw, n)
        except ValueError:
            if attempt == 0:
                user += f"\n注意：請務必輸出剛好 {n} 個候選的 JSON 陣列。"
            else:
                raise


def _parse_candidates(raw: str, n: int) -> list[str]:
    """Extract list[str] from LLM output; retry-tolerant."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip().strip('",') for line in raw.splitlines() if line.strip().strip('",')]
        result = [line for line in lines if len(line) > 5][:n]

    if not isinstance(result, list):
        raise ValueError(f"Expected JSON array from planner, got: {type(result)}")

    candidates = [str(x) for x in result if x]
    if len(candidates) < n:
        raise ValueError(f"Planner returned {len(candidates)} candidates, expected {n}")

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

    Returns a list of `src.social_studies.schemas.CreativeBrief` objects of
    length `count` (padded from survivors) or an empty list when none of the
    LLM's briefs pass validation. Raises `ValueError` when the LLM response
    cannot be parsed as a JSON array at all — callers must catch and fall
    back to briefless prompts.
    """
    from src.social_studies.schemas import CreativeBrief

    system = system_prompt.format(n=count, learning_stage=learning_stage)
    user = user_prompt_template.format(
        contexts="、".join(sampled_contexts),
        count=count,
        learning_content="、".join(learning_content_pool) or "（未指定）",
        core_question=core_question or "（未指定）",
    )

    raw = client.plan(system, user, purpose="plan_context_angles")
    entries = _parse_brief_candidates(raw)

    allowed = set(sampled_contexts)
    survivors: list[CreativeBrief] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ctx = entry.get("selected_context")
        angle = entry.get("題材_angle") or entry.get("題材角度") or ""
        hooks = entry.get("framing_hooks") or []
        if not ctx or ctx not in allowed or not angle:
            continue
        if not isinstance(hooks, list):
            hooks = []
        try:
            survivors.append(CreativeBrief(
                selected_context=ctx,
                題材_angle=str(angle),
                framing_hooks=[str(h) for h in hooks if h],
            ))
        except Exception:
            continue

    if not survivors:
        return []
    if len(survivors) >= count:
        return survivors[:count]
    # Pad the tail by cycling through survivors so every slot has a brief.
    padded = list(survivors)
    i = 0
    while len(padded) < count:
        padded.append(survivors[i % len(survivors)])
        i += 1
    return padded


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
