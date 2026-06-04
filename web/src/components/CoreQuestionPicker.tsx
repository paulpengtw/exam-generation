import { useState } from "react";
import { planCoreQuestions } from "../api/client";
import { useT } from "../i18n/useT";

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    setLoading(true);
    setError(null);
    setCandidates([]);
    onClear();
    try {
      const res = await planCoreQuestions({
        topic,
        subject,
        subject_filter: subjectFilter ? [subjectFilter] : undefined,
        grade,
      });
      setCandidates(res.candidates);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("[plan-core-questions]", e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={handleFetch}
        disabled={!topic.trim() || loading}
        className={`inline-flex items-center gap-2 rounded border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
          error
            ? "border-red-500 bg-red-50 text-red-700 hover:bg-red-100"
            : "border-blue-600 bg-white text-blue-600 hover:bg-blue-50"
        }`}
      >
        {loading && (
          <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
        )}
        {loading ? t("form.plan_btn_loading") : t("form.plan_btn")}
      </button>

      {error && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm">
          <p className="font-medium text-red-700">⚠ {t("form.picker_error")}{error}</p>
          <button
            type="button"
            onClick={handleFetch}
            className="mt-1 text-red-700 underline hover:no-underline"
          >
            {t("form.picker_retry")}
          </button>
        </div>
      )}

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
