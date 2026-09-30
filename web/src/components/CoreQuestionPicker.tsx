import { useMemo, useState } from "react";
import { planCoreQuestions, type AvailableModels } from "../api/client";
import { useT } from "../i18n/useT";
import { clampPickerEffort } from "./pickerEffortClamp";
import {
  ActionButton,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";

// Keep this above the server LLM_TIMEOUT_SECONDS bound (600 seconds by default).
const CORE_QUESTION_PLANNER_TIMEOUT_MS = 630_000;

// Server fallback roster for the effort dropdown when the effective model has no entry.
// Matches _EFFORT_LEVELS.get(model, [...]) in server/generate/routes.py.
const UNKNOWN_MODEL_EFFORT_LEVELS = ["low", "medium", "high", "max"];

export interface CoreQuestionPickerProps {
  topic: string;
  subject?: string;
  subjectFilter?: string;
  grade?: number;
  onPick: (coreQuestion: string) => void;
  onClear: () => void;
  pickedValue: string | null;
  /** Available models from GET /api/models. When provided, shows a model/effort selector. */
  models?: AvailableModels | null;
  /** Currently selected planner model for this picker (session-only, unpersisted).
   *  Defaults to "gemini-3.1-pro-preview". ParamForm initialises this to that value. */
  pickerModelPlan?: string;
  /** Currently selected effort level for this picker (session-only, unpersisted). */
  pickerEffortPlan?: string;
  onPickerModelPlanChange?: (value: string) => void;
  onPickerEffortPlanChange?: (value: string) => void;
}

export default function CoreQuestionPicker({
  topic,
  subject,
  subjectFilter,
  grade,
  onPick,
  onClear,
  pickedValue,
  models,
  pickerModelPlan = "",
  pickerEffortPlan = "",
  onPickerModelPlanChange,
  onPickerEffortPlanChange,
}: CoreQuestionPickerProps) {
  const t = useT();
  const [candidates, setCandidates] = useState<string[]>([]);

  // Effort levels available for the currently selected picker model.
  // When pickerModelPlan is "" (server default), use defaults.plan's roster.
  // Falls back to the server's UNKNOWN_MODEL_EFFORT_LEVELS for models not in the roster.
  const pickerEffortLevels = useMemo(() => {
    if (!models?.effort) return [];
    const effectiveModel = pickerModelPlan || models.defaults.plan;
    return (effectiveModel && models.effort[effectiveModel])
      ? models.effort[effectiveModel]
      : UNKNOWN_MODEL_EFFORT_LEVELS;
  }, [models, pickerModelPlan]);

  // Only send model_plan when models have loaded and the selection is in the allowed list.
  const effectivePickerModel =
    models && pickerModelPlan && models.allowed.includes(pickerModelPlan)
      ? pickerModelPlan
      : undefined;

  const feedback = useActionFeedback({
    action: (signal: AbortSignal) => planCoreQuestions({
      topic,
      subject,
      subject_filter: subjectFilter ? [subjectFilter] : undefined,
      grade,
      model_plan: effectivePickerModel,
      effort_plan: pickerEffortPlan || undefined,
    }, signal),
    genericError: t("form.plan_error"),
    timeoutMs: CORE_QUESTION_PLANNER_TIMEOUT_MS,
    onSuccess: (res) => setCandidates(res.candidates),
  });

  function handleFetch() {
    setCandidates([]);
    onClear();
  }

  const showModelSelector = !!(models && models.allowed.length > 0);

  return (
    <div className="space-y-3">
      {showModelSelector && (
        <div className="flex flex-wrap gap-2">
          <label className="flex flex-col gap-1 text-xs text-gray-700">
            <span>{t("form.picker_model_plan_label")}</span>
            <select
              aria-label={t("form.picker_model_plan_label")}
              value={pickerModelPlan}
              onChange={(e) => {
                const newModel = e.target.value;
                onPickerModelPlanChange?.(newModel);
                // Clamp the effort to what the new model supports (handles "" → defaults.plan).
                if (models && pickerEffortPlan) {
                  const clamped = clampPickerEffort(models, newModel, pickerEffortPlan);
                  if (clamped !== pickerEffortPlan) {
                    onPickerEffortPlanChange?.(clamped);
                  }
                }
              }}
              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">
                {t("params.model_default_option")} ({models.defaults.plan})
              </option>
              {models.allowed.map((m) => (
                <option key={`picker-plan-${m}`} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          {pickerEffortLevels.length > 0 && (
            <label className="flex flex-col gap-1 text-xs text-gray-700">
              <span>{t("form.picker_effort_plan_label")}</span>
              <select
                aria-label={t("form.picker_effort_plan_label")}
                value={pickerEffortPlan}
                onChange={(e) => onPickerEffortPlanChange?.(e.target.value)}
                className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
              >
                {pickerEffortLevels.map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <ActionButton
          feedback={feedback}
          label={t("form.plan_btn")}
          pendingLabel={t("form.plan_btn_loading")}
          onPress={handleFetch}
          disabled={!topic.trim()}
          variant="outline"
          className={feedback.reason
            ? "border-red-500 bg-red-50 text-red-700 hover:bg-red-100"
            : "border-blue-600 bg-white text-blue-600 hover:bg-blue-50"}
        />

        <button
          type="button"
          onClick={() => {
            onPick(topic.trim());
            setCandidates([]);
          }}
          disabled={!topic.trim() || feedback.state === "pending"}
          className="inline-flex items-center gap-2 rounded border border-green-600 bg-white px-3 py-1.5 text-sm font-medium text-green-700 hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("form.custom_question_btn")}
        </button>
      </div>

      <InlineFailureNotice
        reason={feedback.reason}
        onRetry={feedback.retry}
        onDismiss={feedback.dismiss}
        retryLabel={t("form.picker_retry")}
      />

      {candidates.length > 0 && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-700">{t("form.picker_heading")}</legend>
          {candidates.map((c, i) => (
            <label
              key={i}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors duration-quick ease-signature ${
                pickedValue === c
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-200 bg-white hover:border-gray-300"
              }`}
            >
              <input
                type="radio"
                name="core_question_candidate"
                value={c}
                checked={pickedValue === c}
                onChange={() => onPick(c)}
                className="mt-0.5 shrink-0 accent-blue-600"
              />
              <span className="text-sm text-gray-800">{c}</span>
            </label>
          ))}
        </fieldset>
      )}
    </div>
  );
}
