"""NS sampler: difficulty is accepted-and-ignored (#282).

Formerly asserted that difficulty was stored on SampledParams; after issue
#282, 自然科學 no longer carries a difficulty field — Reporting Scale is the
sole demand signal.  The sampler must still accept the kwarg (for backward
compatibility with server/generate/subjects.py which passes params.difficulty)
but must silently discard it.
"""

from __future__ import annotations

from src.natural_sciences.sampler import sample_params


def test_ns_sampler_has_no_difficulty_field():
    params = sample_params(seed=1)
    assert not hasattr(params, "difficulty"), (
        "SampledParams must not expose a difficulty field for NS (#282)"
    )


def test_ns_sampler_accepts_difficulty_kwarg_without_error():
    """Backward-compat: difficulty= accepted but discarded."""
    for v in ("easy", "medium", "hard", None):
        p = sample_params(seed=1, difficulty=v)
        assert p is not None
