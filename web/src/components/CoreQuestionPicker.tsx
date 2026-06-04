import { useState } from "react";
import { planCoreQuestions } from "../api/client";
import { useT } from "../i18n/useT";

export interface CoreQuestionPickerProps {
  topic: string;
  subjectFilter?: string;
  grade?: number;
  onPick: (coreQuestion: string) => void;
  onClear: () => void;
  pickedValue: string | null;
}

export default function CoreQuestionPicker({
  topic,
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
        subject_filter: subjectFilter ? [subjectFilter] : undefined,
        grade,
      });
      setCandidates(res.candidates);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
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
        className="inline-flex items-center gap-2 rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
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
        <p className="text-sm text-red-600">{t("form.picker_error")}{error}</p>
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
