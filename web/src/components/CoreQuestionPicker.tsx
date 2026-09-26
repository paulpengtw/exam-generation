import { useState } from "react";
import { planCoreQuestions } from "../api/client";
import { useT } from "../i18n/useT";
import {
  ActionButton,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";

// Keep this above the server LLM_TIMEOUT_SECONDS bound (600 seconds by default).
const CORE_QUESTION_PLANNER_TIMEOUT_MS = 630_000;

export interface CoreQuestionPickerProps {
  topic: string;
  subject?: string;
  subjectFilter?: string;
  grade?: number;
  onPick: (coreQuestion: string) => void;
  onClear: () => void;
  pickedValue: string | null;
}

export default function CoreQuestionPicker({
  topic,
  subject,
  subjectFilter,
  grade,
  onPick,
  onClear,
  pickedValue,
}: CoreQuestionPickerProps) {
  const t = useT();
  const [candidates, setCandidates] = useState<string[]>([]);

  const feedback = useActionFeedback({
    action: (signal: AbortSignal) => planCoreQuestions({
      topic,
      subject,
      subject_filter: subjectFilter ? [subjectFilter] : undefined,
      grade,
    }, signal),
    genericError: t("form.plan_error"),
    timeoutMs: CORE_QUESTION_PLANNER_TIMEOUT_MS,
    onSuccess: (res) => setCandidates(res.candidates),
  });

  function handleFetch() {
    setCandidates([]);
    onClear();
  }

  return (
    <div className="space-y-3">
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
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
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
