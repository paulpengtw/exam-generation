"""At least 2 few-shot examples per subject must include realistic 誘答分析.

Key shape is asserted, not just non-emptiness: the documented prompt contract
(see src/context_builder.py, src/social_studies/context_builder.py,
src/natural_sciences/context_builder.py) requires 誘答分析 to be a *flat*
dict keyed by option label — "A"/"B"/"C"/"D" (or NS "A是"/"A非"-style for
complex multiple-choice statements) or the constructed-response escape hatch
"常見錯誤". Nested per-question dicts or keys that bake the answer into the
label (e.g. "問題1", "敘述1（正確答案：是）") are schema violations because
few-shot examples get dumped verbatim into sub-generator prompts — the model
learns whatever shape it sees here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ALLOWED_KEY = re.compile(r"^[A-D](是|非)?$|^常見錯誤$")


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


def _is_conformant(distractor: dict) -> bool:
    """Non-empty flat dict whose every key matches the documented label shape."""
    if not isinstance(distractor, dict) or not distractor:
        return False
    return all(
        isinstance(k, str) and isinstance(v, str) and _ALLOWED_KEY.match(k) and v.strip()
        for k, v in distractor.items()
    )


def _count_with_distractor(questions: list[dict]) -> int:
    n = 0
    for q in questions:
        distractor = q.get("誘答分析")
        if isinstance(distractor, dict) and distractor:
            assert _is_conformant(distractor), (
                f"誘答分析 keys must be flat and match {_ALLOWED_KEY.pattern!r}, "
                f"got keys: {list(distractor.keys())}"
            )
            n += 1
            continue
        for sq in q.get("subquestions", []) or []:
            sq_distractor = sq.get("誘答分析") if isinstance(sq, dict) else None
            if isinstance(sq_distractor, dict) and sq_distractor:
                assert _is_conformant(sq_distractor), (
                    f"誘答分析 keys must be flat and match {_ALLOWED_KEY.pattern!r}, "
                    f"got keys: {list(sq_distractor.keys())}"
                )
                n += 1
                break
    return n


def test_math_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_math_questions()) >= 2


def test_ss_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ss_questions()) >= 2


def test_ns_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ns_questions()) >= 2
