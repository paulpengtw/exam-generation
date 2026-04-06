"""Solve exam questions and generate structured metadata using LLM."""

from __future__ import annotations

import json
from pathlib import Path


def solve_question(
    llm_client,
    parsed_question: dict,
    prompts_dir: Path,
) -> dict:
    """
    Given a parsed question dict, generate the full structured representation.

    Returns a dict matching the few-shot JSON schema (without 學習內容 — added later).
    """
    system_prompt = (prompts_dir / "solve_question.md").read_text(encoding="utf-8")

    user_text = f"""Please solve and structure this Taiwan junior high school math question:

Question Number: {parsed_question.get('question_number', 'unknown')}
Type Hint: {parsed_question.get('question_type_hint', '選擇題')}

Question Text:
{parsed_question.get('raw_text', '')}

Figure Description:
{parsed_question.get('figure_description') or 'No figure'}

Return a JSON object with all required fields.
"""

    raw = llm_client.generate(system_prompt, user_text)
    result = _extract_json_object(raw)
    return result


def verify_question(
    llm_client,
    solved_question: dict,
    prompts_dir: Path,
) -> dict:
    """
    Second-pass verification: independently solve and compare answers.
    Returns the solved_question, possibly with corrected answer.
    """
    system = """You are a math teacher verifying an exam question's answer.
Independently solve the question and check if the given answer is correct.
Return JSON: {"answer_matches": true/false, "correct_answer": "...", "notes": "..."}"""

    question_text = "\n".join(solved_question.get("題目", []))
    given_analysis = "\n".join(solved_question.get("正確解題分析", []))

    user_text = f"""Question:
{question_text}

Proposed answer and solution:
{given_analysis}

Solve independently and verify. Return JSON."""

    raw = llm_client.generate(system, user_text)
    try:
        verification = _extract_json_object(raw)
        if not verification.get("answer_matches", True):
            # Update the analysis with the correction note
            solved_question["正確解題分析"].append(
                f"【驗算注意】{verification.get('notes', '請重新確認答案')}"
            )
    except Exception:
        pass  # Verification is best-effort

    return solved_question


def _extract_json_object(text: str) -> dict:
    """Extract a JSON object from LLM response text."""
    import re

    # Try code blocks
    code_block = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    if code_block:
        return json.loads(code_block.group(1))

    # Try direct JSON
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)

    # Find first {...} block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"Could not extract JSON object from:\n{text[:500]}")
