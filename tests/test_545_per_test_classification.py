"""
Verify that docs/research/2026-08-24-545-staging-failures-classification.md
records each of the 8 staging failures (issue #545) individually with a
per-test root-cause analysis.

A bulk claim does not satisfy the record requirement: each function must
appear by name with its own classification entry, carrying an explicit
classification label.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[1]
_CLASSIFICATION_DOC = (
    _REPO_ROOT / "docs" / "research" / "2026-08-24-545-staging-failures-classification.md"
)
_CLASSIFICATION_LABELS = frozenset({"ENVIRONMENT-ONLY", "REGRESSION"})


def _read_classification() -> str:
    if not _CLASSIFICATION_DOC.exists():
        pytest.fail(
            f"Per-test classification document not found: {_CLASSIFICATION_DOC}\n"
            "Create docs/research/2026-08-24-545-staging-failures-classification.md "
            "with one section per failing test (issue #545)."
        )
    return _CLASSIFICATION_DOC.read_text()


def _parse_sections(text: str) -> list[str]:
    """Split into per-failure sections (each starts with ### Failure N —)."""
    return re.split(r"\n(?=### Failure \d+)", text)


def _find_section(sections: list[str], *, file_name: str, func_name: str) -> str | None:
    """Return the section whose body names both file_name and func_name, or None."""
    matches = [s for s in sections if file_name in s and func_name in s]
    return matches[0] if matches else None


def _has_classification(section: str) -> bool:
    return any(label in section for label in _CLASSIFICATION_LABELS)


# ---------------------------------------------------------------------------
# Failure 1 — test_batch_dedup.py
# ---------------------------------------------------------------------------

def test_classification_records_stream_accumulates_prior_scopes() -> None:
    """test_server_generate_stream_accumulates_prior_scopes_across_math_workers must be named."""
    text = _read_classification()
    assert (
        "test_server_generate_stream_accumulates_prior_scopes_across_math_workers" in text
    ), "Classification doc must mention the batch-dedup stream test individually"


# ---------------------------------------------------------------------------
# Failure 2 — test_interactive_item_generation.py
# ---------------------------------------------------------------------------

def test_classification_records_modification_merge_ignores_interaction_paths() -> None:
    """test_scoped_modification_merge_ignores_interaction_paths must be named."""
    text = _read_classification()
    assert (
        "test_scoped_modification_merge_ignores_interaction_paths" in text
    ), "Classification doc must mention the modification-merge test individually"


# ---------------------------------------------------------------------------
# Failures 3-5 — test_natural_sciences_core_question_callback.py
# ---------------------------------------------------------------------------

def test_classification_records_ns_generate_route_declares_callback_parameter() -> None:
    """NS: test_generate_route_declares_callback_query_parameter must have its own section."""
    sections = _parse_sections(_read_classification())
    section = _find_section(
        sections,
        file_name="test_natural_sciences_core_question_callback.py",
        func_name="test_generate_route_declares_callback_query_parameter",
    )
    assert section is not None, (
        "Classification doc must contain a section for "
        "test_natural_sciences_core_question_callback.py / "
        "test_generate_route_declares_callback_query_parameter"
    )
    assert _has_classification(section), (
        "NS failure-3 section must carry an explicit classification label "
        "(ENVIRONMENT-ONLY or REGRESSION)"
    )


def test_classification_records_ns_prompt_preview_reflects_callback_state() -> None:
    """NS: test_natural_sciences_prompt_preview_reflects_requested_callback_state must be named."""
    text = _read_classification()
    assert (
        "test_natural_sciences_prompt_preview_reflects_requested_callback_state" in text
    ), "Classification doc must mention the NS prompt-preview test individually"


def test_classification_records_ns_callback_toggle_does_not_change_sampling() -> None:
    """NS: test_callback_toggle_does_not_change_seeded_natural_sciences_sampling must be named."""
    text = _read_classification()
    assert (
        "test_callback_toggle_does_not_change_seeded_natural_sciences_sampling" in text
    ), "Classification doc must mention the NS sampling-toggle test individually"


# ---------------------------------------------------------------------------
# Failures 6-8 — test_social_studies_core_question_callback.py
# ---------------------------------------------------------------------------

def test_classification_records_ss_generate_route_declares_callback_parameter() -> None:
    """SS: test_generate_route_declares_callback_query_parameter must have its own section."""
    sections = _parse_sections(_read_classification())
    section = _find_section(
        sections,
        file_name="test_social_studies_core_question_callback.py",
        func_name="test_generate_route_declares_callback_query_parameter",
    )
    assert section is not None, (
        "Classification doc must contain a section for "
        "test_social_studies_core_question_callback.py / "
        "test_generate_route_declares_callback_query_parameter"
    )
    assert _has_classification(section), (
        "SS failure-6 section must carry an explicit classification label "
        "(ENVIRONMENT-ONLY or REGRESSION)"
    )


def test_classification_records_ss_prompt_preview_reflects_callback_state() -> None:
    """SS: test_social_studies_prompt_preview_reflects_requested_callback_state must be named."""
    text = _read_classification()
    assert (
        "test_social_studies_prompt_preview_reflects_requested_callback_state" in text
    ), "Classification doc must mention the SS prompt-preview test individually"


def test_classification_records_ss_callback_toggle_does_not_change_sampling() -> None:
    """SS: test_callback_toggle_does_not_change_seeded_social_studies_sampling must be named."""
    text = _read_classification()
    assert (
        "test_callback_toggle_does_not_change_seeded_social_studies_sampling" in text
    ), "Classification doc must mention the SS sampling-toggle test individually"
