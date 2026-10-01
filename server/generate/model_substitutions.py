"""Helper for computing model-tier substitutions caused by the Fable downgrade switch.

Issue #943, task 3.3 — ``model_substitutions(params, config)`` uses the same
effective-tier resolution as ``_check_generation_admission`` in routes.py so
that the stored ``model_substitutions`` entry is derived from the same logic
that actually governs dispatching.

The function returns a dict mapping tier names to ``{requested, ran}`` pairs
for every tier where a substitution occurred.  The dict is empty (and must not
be stored) when the switch is off or no tier uses a Fable model.
"""

from __future__ import annotations

from typing import Any

from src.config import Config


def model_substitutions(
    params: Any,
    config: Config,
) -> dict[str, dict[str, str]]:
    """Compute per-tier substitution info from the effective-tier resolution.

    The resolution mirrors ``_check_generation_admission`` in routes.py:
        effective_<tier>_model = params.model_<tier> or config.model_<tier> or …

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

    # Resolve the effective model for each tier — mirrors _check_generation_admission.
    effective_plan_model: str = getattr(params, "model_plan", None) or config.model_plan
    effective_execute_model: str = getattr(params, "model_execute", None) or config.model_execute
    # verify and correct chain off execute (honours per-request overrides).
    effective_verify_model: str = (
        getattr(params, "model_verify", None)
        or config.model_verify
        or effective_execute_model
    )
    effective_correct_model: str = (
        getattr(params, "model_correct", None)
        or config.model_correct
        or effective_execute_model
    )

    tiers: dict[str, str] = {
        "plan": effective_plan_model,
        "execute": effective_execute_model,
        "verify": effective_verify_model,
        "correct": effective_correct_model,
    }

    result: dict[str, dict[str, str]] = {}
    for tier, requested in tiers.items():
        ran = config.dispatch_model(requested)
        if ran != requested:
            result[tier] = {"requested": requested, "ran": ran}
    return result
