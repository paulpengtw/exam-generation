import type { AvailableModels } from "../api/client";

// Server fallback for models not listed in _EFFORT_LEVELS: matches
// _EFFORT_LEVELS.get(model, ["low", "medium", "high", "max"]) in server/generate/routes.py.
const UNKNOWN_MODEL_EFFORT_LEVELS = ["low", "medium", "high", "max"];

/**
 * Clamp `effort` to a level supported by `model` (or `models.defaults.plan` when `model` is "").
 *
 * - When `model` is "" the effective model resolves to `models.defaults.plan`.
 * - When the effective model has no roster entry in `models.effort`, falls back to
 *   ["low", "medium", "high", "max"] matching the server's _EFFORT_LEVELS default.
 * - Returns `effort` unchanged when `models.effort` is absent or the effort is already valid.
 * - Otherwise prefers "medium", then the first available level.
 */
export function clampPickerEffort(models: AvailableModels, model: string, effort: string): string {
  if (!effort || !models.effort) return effort;
  const effectiveModel = model || models.defaults.plan;
  const levels: string[] = (effectiveModel && models.effort[effectiveModel])
    ? models.effort[effectiveModel]
    : UNKNOWN_MODEL_EFFORT_LEVELS;
  if (levels.includes(effort)) return effort;
  return levels.includes("medium") ? "medium" : (levels[0] ?? effort);
}
