"""Validate that per-option 誘答分析 keys line up with the option labels in 題目.

Used by all three subject verifiers as a details-level advisory: warnings are
appended to VerificationResult.details but NEVER flip passed to False.
"""

from __future__ import annotations

import re

# Matches (A)–(Z) and full-width （A）–（Z） option-label markers in question text.
_OPTION_LABEL_RE = re.compile(r"[(（]\s*([A-Z])\s*[)）]")


def _extract_option_labels(question_text: str) -> set[str]:
    if not isinstance(question_text, str):
        return set()
    return {m.group(1) for m in _OPTION_LABEL_RE.finditer(question_text)}


def validate_distractor_keys(
    question_text: str, analysis: dict[str, str] | None
) -> list[str]:
    """Return human-readable warnings about mismatched 誘答分析 keys.

    Rules:
    - Empty / non-dict input → no warnings.
    - When question_text contains (A)-(D) style labels, every extracted label
      must appear in the analysis dict, and every analysis key must correspond
      to an extracted label (extras trigger a warning).
    - When the question has no (X) labels (constructed-response, 是非題 with
      是/非 keys, matching-type items), the dict is passed through without
      warnings — reviewers can still see the payload.
    """
    if not isinstance(analysis, dict) or not analysis:
        return []

    labels = _extract_option_labels(question_text)
    if not labels:
        return []

    warnings: list[str] = []
    keys = set(analysis.keys())
    missing = sorted(labels - keys)
    extra = sorted(keys - labels - {"常見錯誤"})
    if missing:
        warnings.append(
            f"誘答分析缺少選項 {', '.join(missing)}（題目中有此選項但未提供分析）"
        )
    if extra:
        warnings.append(
            f"誘答分析出現題目未定義的鍵 {', '.join(extra)}"
        )
    return warnings
