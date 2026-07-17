"""Unit tests for the distractor-key validator."""

from __future__ import annotations


def test_returns_empty_when_dict_is_empty() -> None:
    from src.common.distractor import validate_distractor_keys

    assert validate_distractor_keys("What is 2+2? (A) 3 (B) 4 (C) 5 (D) 6", {}) == []


def test_returns_empty_when_keys_match_option_labels() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    analysis = {
        "A": "誤讀題意",
        "B": "正確答案：4。",
        "C": "概念混淆",
        "D": "過度推論",
    }
    assert validate_distractor_keys(text, analysis) == []


def test_warns_when_analysis_has_extra_key() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x", "C": "x", "D": "x", "E": "x"})
    assert len(warnings) == 1
    assert "E" in warnings[0]


def test_warns_when_analysis_is_missing_key() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x", "C": "x"})
    assert len(warnings) == 1
    assert "D" in warnings[0]


def test_extracts_uppercase_labels_only_and_tolerates_full_width_parens() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n（A）3\n（B）4"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x"})
    assert warnings == []


def test_true_false_labels_pass_through() -> None:
    """是非題 uses 是 / 非 as keys; no options in text → no warnings expected."""
    from src.common.distractor import validate_distractor_keys

    analysis = {"是": "正確答案：...", "非": "..."}
    warnings = validate_distractor_keys("下列敘述是否正確：2+2=4", analysis)
    assert warnings == []


def test_never_raises_on_non_dict() -> None:
    from src.common.distractor import validate_distractor_keys

    assert validate_distractor_keys("text", None) == []  # type: ignore[arg-type]
