"""Shared verification implementation for NS and SS subjects.

Both the social-studies and natural-sciences verifiers delegate their
core LLM-call + parsing + distractor-warning logic here.  Subject-specific
behaviour (curriculum-code hard-reject for NS, web-search fact-check for SS)
is expressed as ``post_verify_hooks`` — callables run *after* the LLM verdict
is parsed, each receiving the question, the in-progress
``VerificationResult``, and the LLM client, and returning the (possibly
mutated) result.

Hook contract
-------------
Each hook has signature::

    (question: Any, result: VerificationResult, client: LLMClient) -> VerificationResult

A hook may:

- Mutate ``result.details`` (append text).
- Force ``result.passed = False``.
- Set subject-specific fields (e.g. SS's ``result.fact_check``).
- Return the mutated result unchanged or replaced.

Hooks are executed in order; the first hook to force ``passed=False`` does
not prevent subsequent hooks from running.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from src.common.distractor import validate_distractor_keys
from src.llm_client import LLMClient, extract_json

# Callable: (question, VerificationResult, LLMClient) -> VerificationResult
PostVerifyHook = Callable[[Any, Any, "LLMClient"], Any]


def _parse_chart_verif(cv: dict, chart_verif_cls: type) -> Any:
    return chart_verif_cls(
        chart_data_match=cv.get("chart_data_match", False),
        chart_labels_correct=cv.get("chart_labels_correct", False),
        chart_details=cv.get("chart_details", ""),
    )


def verify_question_common(
    client: LLMClient,
    question: Any,
    system_prompt: str,
    user_prompt: str,
    verification_result_cls: type,
    chart_verif_cls: type,
    chart_image_path: str | None = None,
    post_verify_hooks: list[PostVerifyHook] | None = None,
) -> Any:
    """Shared verifier core for questions with subquestions.

    The caller is responsible for:

    - File-existence check on ``chart_image_path`` (set to ``None`` when the
      file is absent so the call falls back to text-only).
    - Building ``system_prompt`` (curriculum prefix prepended if required).
    - Building ``user_prompt`` (including the ``## 附圖`` section when
      ``chart_image_path`` is not ``None``).

    This function handles the LLM call, JSON extraction, per-subquestion
    distractor-key audit (advisory — never flips ``passed``), and
    subject-specific post-verify hooks.

    Args:
        client: LLM client.
        question: Subject exam-question object (must have ``.subquestions``).
        system_prompt: Full system prompt (curriculum prefix already prepended
            by the caller when required).
        user_prompt: Full user prompt (already built by the caller, including
            the ``## 附圖`` section if relevant).
        verification_result_cls: Subject's ``VerificationResult`` class.
        chart_verif_cls: Subject's ``ChartVerificationResult`` class.
        chart_image_path: Path to a rendered chart PNG passed through to
            ``client.generate_with_image``; ``None`` for text-only calls.
        post_verify_hooks: Callables run after the LLM verdict is parsed.
            Executed in declaration order.

    Returns:
        A ``VerificationResult`` instance of ``verification_result_cls``.
    """
    try:
        raw = client.generate_with_image(
            system_prompt, user_prompt, image_path=chart_image_path, purpose="verify"
        )
        result_dict = extract_json(raw)

        cv = result_dict.get("chart_verification")
        chart_verif = _parse_chart_verif(cv, chart_verif_cls) if isinstance(cv, dict) else None

        # Non-blocking distractor-key audit — advisory only, never flips passed.
        # Format: "第N題：<warning>" entries joined with "；".
        all_warnings: list[str] = []
        for sq in question.subquestions:
            for w in validate_distractor_keys(sq.題目, sq.誘答分析):
                all_warnings.append(f"第{sq.序號}題：{w}")

        details = result_dict.get("details", "")
        if all_warnings:
            details = details.rstrip()
            details += "\n\n[誘答分析提醒] " + "；".join(all_warnings)

        verification = verification_result_cls(
            passed=result_dict.get("passed", False),
            answer_match=result_dict.get("answer_match", False),
            details=details,
            my_answer=result_dict.get("my_answer", ""),
            provided_answer=result_dict.get("provided_answer", ""),
            chart_verification=chart_verif,
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # On parse failure return immediately — hooks don't run.
        return verification_result_cls(
            passed=False,
            answer_match=False,
            details=f"Verification failed to parse LLM response: {e}",
        )

    # Run subject-specific post-verify hooks in declaration order.
    for hook in (post_verify_hooks or []):
        verification = hook(question, verification, client)

    return verification
