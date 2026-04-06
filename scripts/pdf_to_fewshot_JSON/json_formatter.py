"""Format solved questions into few-shot JSON files, grouped by style."""

from __future__ import annotations

import json
from pathlib import Path


VALID_STYLES = {"text_only", "with_chart", "with_image", "creative_scenario"}
VALID_CONTEXTS = {"個人", "社會時事", "科學", "職業", "建築與藝術", "數學文字情境"}
VALID_SET_TYPES = {"單一題", "題組題"}
VALID_QUESTION_TYPES = {"選擇題", "是非題", "封閉式建構反應題", "開放式建構反應題"}
VALID_THINKING = {"形成", "運用", "詮釋評估"}


def format_question(
    solved: dict,
    learning_content: list[dict],
    question_number: str,
) -> dict | None:
    """
    Convert a solved question + curriculum codes into the few-shot JSON schema.

    Returns None if the question is missing required fields.
    """
    style = solved.get("style", "text_only")
    if style not in VALID_STYLES:
        style = "text_only"

    # Build the question object
    question = {
        "情境": solved.get("情境", "數學文字情境"),
        "題型種類": solved.get("題型種類", "單一題"),
        "題型": solved.get("題型", "選擇題"),
        "數學思考": _validate_thinking(solved.get("數學思考", ["運用"])),
        "學習內容": learning_content,
        "題目": solved.get("題目", []),
        "正確解題分析": solved.get("正確解題分析", []),
    }

    # Validate required fields
    if not question["題目"] or not question["正確解題分析"]:
        return None

    if question["情境"] not in VALID_CONTEXTS:
        question["情境"] = "數學文字情境"
    if question["題型種類"] not in VALID_SET_TYPES:
        question["題型種類"] = "單一題"
    if question["題型"] not in VALID_QUESTION_TYPES:
        question["題型"] = "選擇題"

    # Include chart_spec for non-text_only styles
    if style in ("with_chart", "with_image") and solved.get("chart_spec"):
        question["chart_spec"] = solved["chart_spec"]

    return {
        "style": style,
        "description": solved.get("description", question_number),
        "question": question,
    }


def group_by_style(formatted_questions: list[dict]) -> dict[str, list[dict]]:
    """Group formatted questions by their style."""
    groups: dict[str, list[dict]] = {
        "text_only": [],
        "with_chart": [],
        "with_image": [],
        "creative_scenario": [],
    }
    for q in formatted_questions:
        style = q.get("style", "text_only")
        if style in groups:
            groups[style].append(q)
    return groups


def save_to_files(
    grouped: dict[str, list[dict]],
    output_dir: Path,
    exam_name: str,
) -> dict[str, Path]:
    """
    Save each style group to a JSON file.

    Files are written to:
        output_dir/{style}/{exam_name}_questions.json

    Returns a dict mapping style -> output file path.
    """
    written: dict[str, Path] = {}

    for style, questions in grouped.items():
        if not questions:
            continue

        style_dir = output_dir / style
        style_dir.mkdir(parents=True, exist_ok=True)

        out_path = style_dir / f"{exam_name}_questions.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)

        written[style] = out_path
        print(f"  Wrote {len(questions)} questions to {out_path}")

    return written


def _validate_thinking(thinking: list) -> list[str]:
    """Ensure thinking values are valid, deduplicated, preserving order."""
    seen = set()
    result = []
    for t in thinking:
        if t in VALID_THINKING and t not in seen:
            result.append(t)
            seen.add(t)
    return result if result else ["運用"]
