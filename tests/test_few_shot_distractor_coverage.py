"""At least 2 few-shot examples per subject must include realistic 誘答分析."""

from __future__ import annotations

import json
from pathlib import Path


def _iter_math_questions() -> list[dict]:
    root = Path("data/few_shot")
    out: list[dict] = []
    for f in root.glob("*/*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _iter_ss_questions() -> list[dict]:
    root = Path("data/social_studies/few_shot")
    out: list[dict] = []
    for f in root.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _iter_ns_questions() -> list[dict]:
    root = Path("data/natural_sciences/few_shot")
    out: list[dict] = []
    for f in root.glob("*/*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _count_with_distractor(questions: list[dict]) -> int:
    n = 0
    for q in questions:
        if isinstance(q.get("誘答分析"), dict) and q["誘答分析"]:
            n += 1
            continue
        for sq in q.get("subquestions", []) or []:
            if isinstance(sq, dict) and isinstance(sq.get("誘答分析"), dict) and sq["誘答分析"]:
                n += 1
                break
    return n


def test_math_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_math_questions()) >= 2


def test_ss_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ss_questions()) >= 2


def test_ns_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ns_questions()) >= 2
