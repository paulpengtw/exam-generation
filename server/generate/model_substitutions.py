"""Helper for computing model-tier substitutions caused by the Fable downgrade switch.

Issue #943, task 3.3 — ``model_substitutions(params, config)`` uses the same
effective-tier resolution as ``_check_generation_admission`` in routes.py so
that the stored ``model_substitutions`` entry is derived from the same logic
that actually governs dispatching.

The function returns a dict mapping tier names to ``{requested, ran}`` pairs
for every tier where a substitution occurred.  The dict is empty (and must not
be stored) when the switch is off or no tier uses a Fable model.

``effective_tier_models`` is the shared seam: it is called by both this module
and ``_check_generation_admission`` / ``_preview_generate`` in routes.py so
that the resolution logic is never duplicated.
"""

from __future__ import annotations

from typing import Any

from src.config import Config


def effective_tier_models(params: Any, config: Config) -> dict[str, str]:
    """Resolve the effective model for each generation tier.

    Implements the canonical tier resolution rule shared by
    ``_check_generation_admission``, ``_preview_generate``, and
    ``model_substitutions``:

        effective_<tier> = request param or env-var default
        verify / correct additionally fall back to effective_execute

    Args:
        params: A GenerateParams-like object (must expose model_plan,
            model_execute, model_verify, model_correct as str | None).
        config: A Config / ServerConfig instance with model_* fields.

    Returns:
        A dict with keys ``plan``, ``execute``, ``verify``, ``correct``
        mapping each to its resolved model string.
    """
    effective_plan: str = getattr(params, "model_plan", None) or config.model_plan
    effective_execute: str = getattr(params, "model_execute", None) or config.model_execute
    # verify and correct chain off execute (honours per-request overrides).
    effective_verify: str = (
        getattr(params, "model_verify", None)
        or config.model_verify
        or effective_execute
    )
    effective_correct: str = (
        getattr(params, "model_correct", None)
        or config.model_correct
        or effective_execute
    )
    return {
        "plan": effective_plan,
        "execute": effective_execute,
        "verify": effective_verify,
        "correct": effective_correct,
    }


def model_substitutions(
    params: Any,
    config: Config,
) -> dict[str, dict[str, str]]:
    """Compute per-tier substitution info from the effective-tier resolution.

    Uses ``effective_tier_models`` — the shared seam also used by
    ``_check_generation_admission`` — so that the stored substitution entry is
    derived from exactly the same logic that governs dispatching.

    Returns a dict ``{tier: {requested: str, ran: str}}`` containing only the
    tiers that were actually substituted.  Returns ``{}`` when the switch is
    off or no Fable model appears in any tier.

    Args:
        params: A GenerateParams-like object (must expose model_plan,
            model_execute, model_verify, model_correct as str | None).
        config: A Config / ServerConfig instance with fable_downgrade and
            model_* fields.
    """
    if not config.fable_downgrade:
        return {}

    tiers = effective_tier_models(params, config)

    result: dict[str, dict[str, str]] = {}
    for tier, requested in tiers.items():
        ran = config.dispatch_model(requested)
        if ran != requested:
            result[tier] = {"requested": requested, "ran": ran}
    return result
