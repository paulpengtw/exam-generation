"""
Verify that docs/research/2026-08-24-545-staging-failures-classification.md
records each of the 8 staging failures (issue #545) individually with a
per-test root-cause analysis.

A bulk claim does not satisfy the record requirement: each function must
appear by name with its own classification entry.
"""
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[1]
_CLASSIFICATION_DOC = (
    _REPO_ROOT / "docs" / "research" / "2026-08-24-545-staging-failures-classification.md"
)


def _read_classification() -> str:
    if not _CLASSIFICATION_DOC.exists():
        pytest.fail(
            f"Per-test classification document not found: {_CLASSIFICATION_DOC}\n"
            "Create docs/research/2026-08-24-545-staging-failures-classification.md "
            "with one section per failing test (issue #545)."
        )
    return _CLASSIFICATION_DOC.read_text()


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
    """NS: test_generate_route_declares_callback_query_parameter (fastapi dep) must be named."""
    text = _read_classification()
    assert "test_natural_sciences_core_question_callback" in text, (
        "Classification doc must reference the NS callback file"
    )
    assert "test_generate_route_declares_callback_query_parameter" in text, (
        "Classification doc must name the NS route-parameter test individually"
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
    """SS: test_generate_route_declares_callback_query_parameter (fastapi dep) must be named."""
    text = _read_classification()
    assert "test_social_studies_core_question_callback" in text, (
        "Classification doc must reference the SS callback file"
    )
    # The function name is shared with the NS variant; the file-name assertion
    # above distinguishes the two entries.
    assert "test_generate_route_declares_callback_query_parameter" in text, (
        "Classification doc must name the SS route-parameter test individually"
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
