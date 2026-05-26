import { useEffect, useState } from "react";
import { getSchemas, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import CoreQuestionPicker from "./CoreQuestionPicker";

export interface GenerateParams {
  grade: number;
  style: string;
  context: string[];
  set_type: string;
  q_type: string[];
  count: number;
  skip_verify: boolean;
  image_generation_mode: "html" | "gpt_image";
  subject_filter?: string;
  passage?: string;
  options?: string[];
  core_question?: string;
}

export interface ParamFormProps {
  subject?: string;
  onSubmit: (params: GenerateParams) => void;
  disabled: boolean;
}

const TEXT_HINT = "500 字";
const OPTION_HINT = "50 字";

export default function ParamForm({ subject = "math", onSubmit, disabled }: ParamFormProps) {
  const t = useT();
  const [schemas, setSchemas] = useState<Schemas | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [grade, setGrade] = useState<number | "">("");
  const [style, setStyle] = useState<string>("");
  const [context, setContext] = useState<string[]>([]);
  const [setType, setSetType] = useState<string>("");
  const [qType, setQType] = useState<string[]>([]);
  const [count, setCount] = useState<number>(1);
  const [skipVerify, setSkipVerify] = useState<boolean>(false);
  const [imageGenerationMode, setImageGenerationMode] =
    useState<"html" | "gpt_image">("html");
  const [subjectFilter, setSubjectFilter] = useState<string>("");
  const [passage, setPassage] = useState<string>(TEXT_HINT);
  const [options, setOptions] = useState<string[]>([OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]);
  const [topic, setTopic] = useState<string>("");
  const [coreQuestion, setCoreQuestion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSchemas(null);
    setError(null);
    setContext([]);
    setQType([]);
    setImageGenerationMode("html");
    setPassage(TEXT_HINT);
    setOptions([OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]);
    getSchemas(subject)
      .then((s) => {
        if (cancelled) return;
        setSchemas(s);
        if (s.grades.length > 0) setGrade(s.grades[0]);
        if (s.question_style.length > 0) setStyle(s.question_style[0].value);
        if (s.題型種類.length > 0) setSetType(s.題型種類[0].value);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [subject]);

  function toggleMulti(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (grade === "") return;
    const cleanPassage = passage === TEXT_HINT ? undefined : passage;
    const cleanOptions = options.filter((o) => o && o !== OPTION_HINT);
    onSubmit({
      grade,
      style,
      context,
      set_type: setType,
      q_type: qType,
      count,
      skip_verify: skipVerify,
      image_generation_mode: imageGenerationMode,
      subject_filter: subjectFilter || undefined,
      passage: cleanPassage,
      options: cleanOptions.length ? cleanOptions : undefined,
      core_question: coreQuestion || undefined,
    });
  }

  if (error) {
    return <div className="text-red-600">{t("form.error_schemas")}{error}</div>;
  }

  if (!schemas) {
    return (
      <div className="space-y-4 animate-pulse" aria-busy="true" aria-label="Loading form">
        <div>
          <div className="h-3 w-16 rounded bg-gray-200" />
          <div className="mt-2 h-9 w-full rounded bg-gray-100" />
        </div>
        <div>
          <div className="h-3 w-16 rounded bg-gray-200" />
          <div className="mt-2 h-9 w-full rounded bg-gray-100" />
        </div>
        <div>
          <div className="h-3 w-32 rounded bg-gray-200" />
          <div className="mt-2 space-y-1.5">
            <div className="h-4 w-2/3 rounded bg-gray-100" />
            <div className="h-4 w-1/2 rounded bg-gray-100" />
            <div className="h-4 w-3/5 rounded bg-gray-100" />
          </div>
        </div>
        <div>
          <div className="h-3 w-24 rounded bg-gray-200" />
          <div className="mt-2 h-9 w-full rounded bg-gray-100" />
        </div>
        <div className="h-9 w-28 rounded bg-gray-200" />
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium">{t("form.grade")}</label>
        <select
          value={grade}
          onChange={(e) => setGrade(Number(e.target.value))}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          {schemas.grades.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium">{t("form.style")}</label>
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          {schemas.question_style.map((s) => (
            <option key={s.value} value={s.value}>
              {s.value}
            </option>
          ))}
        </select>
      </div>

      <fieldset>
        <legend className="text-sm font-medium">{t("form.context")}</legend>
        <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2 md:grid-cols-3">
          {schemas.情境.map((s) => (
            <label key={s.value} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={context.includes(s.value)}
                onChange={() => setContext((prev) => toggleMulti(prev, s.value))}
              />
              <span>{s.value}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div>
        <label className="block text-sm font-medium">{t("form.set_type")}</label>
        <select
          value={setType}
          onChange={(e) => setSetType(e.target.value)}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          {schemas.題型種類.map((s) => (
            <option key={s.value} value={s.value}>
              {s.value}
            </option>
          ))}
        </select>
      </div>

      <fieldset>
        <legend className="text-sm font-medium">{t("form.q_type")}</legend>
        <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2 md:grid-cols-3">
          {schemas.題型.map((s) => (
            <label key={s.value} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={qType.includes(s.value)}
                onChange={() => setQType((prev) => toggleMulti(prev, s.value))}
              />
              <span>{s.value}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div>
        <label className="block text-sm font-medium">{t("form.count")}</label>
        <input
          type="number"
          min={1}
          max={10}
          value={count}
          onChange={(e) => setCount(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
          className="mt-1 block w-24 border rounded px-2 py-1"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">文本</label>
        <textarea
          value={passage}
          onFocus={() => { if (passage === TEXT_HINT) setPassage(""); }}
          onBlur={() => { if (passage === "") setPassage(TEXT_HINT); }}
          onChange={(e) => setPassage(e.target.value)}
          rows={6}
          className="mt-1 block w-full border rounded px-2 py-1"
        />
      </div>

      <fieldset>
        <legend className="text-sm font-medium">選項</legend>
        <div className="mt-1 space-y-1.5">
          {options.map((opt, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-5 text-sm text-gray-500">{String.fromCharCode(65 + i)}.</span>
              <input
                type="text"
                value={opt}
                onFocus={() => {
                  if (opt === OPTION_HINT) {
                    setOptions((prev) => prev.map((v, j) => j === i ? "" : v));
                  }
                }}
                onBlur={() => {
                  if (options[i] === "") {
                    setOptions((prev) => prev.map((v, j) => j === i ? OPTION_HINT : v));
                  }
                }}
                onChange={(e) => {
                  const v = e.target.value;
                  setOptions((prev) => prev.map((x, j) => j === i ? v : x));
                }}
                className="flex-1 border rounded px-2 py-1"
              />
              <button
                type="button"
                onClick={() => setOptions((prev) => prev.filter((_, j) => j !== i))}
                className="text-sm text-red-600 hover:underline disabled:opacity-40"
                disabled={options.length <= 2}
              >−</button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setOptions((prev) => [...prev, OPTION_HINT])}
            className="text-sm text-blue-600 hover:underline disabled:opacity-40"
            disabled={options.length >= 8}
          >+ 新增選項</button>
        </div>
      </fieldset>

      {subject === "social_studies" && schemas.科目 && schemas.科目.length > 0 && (
        <div>
          <label className="block text-sm font-medium">{t("form.subject_filter")}</label>
          <select
            value={subjectFilter}
            onChange={(e) => setSubjectFilter(e.target.value)}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="">{t("form.subject_filter.all")}</option>
            {schemas.科目.map((s) => (
              <option key={s.value} value={s.value}>
                {s.value}
              </option>
            ))}
          </select>
        </div>
      )}

      {subject === "social_studies" && (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{t("form.topic_label")}</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setCoreQuestion(null);
            }}
            placeholder={t("form.topic_placeholder")}
            className="mt-1 block w-full border rounded px-2 py-1"
          />
          {topic.trim() && (
            <CoreQuestionPicker
              topic={topic}
              subjectFilter={subjectFilter || undefined}
              grade={grade !== "" ? grade : undefined}
              onPick={(q) => setCoreQuestion(q)}
              onClear={() => setCoreQuestion(null)}
              pickedValue={coreQuestion}
            />
          )}
        </div>
      )}

      {subject === "social_studies" && (
        <div>
          <label className="block text-sm font-medium">{t("form.image_generation_mode")}</label>
          <select
            value={imageGenerationMode}
            onChange={(e) =>
              setImageGenerationMode(e.target.value as "html" | "gpt_image")
            }
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="html">{t("form.image_generation_mode_html")}</option>
            <option value="gpt_image">{t("form.image_generation_mode_gpt")}</option>
          </select>
        </div>
      )}

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={skipVerify}
          onChange={(e) => setSkipVerify(e.target.checked)}
        />
        <span className="text-sm">{t("form.skip_verify")}</span>
      </label>

      <button
        type="submit"
        disabled={disabled}
        className="inline-flex w-full items-center justify-center gap-2 rounded bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
      >
        {disabled && (
          <svg
            className="h-4 w-4 animate-spin"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
        )}
        {disabled ? t("form.btn_generating") : t("form.btn_generate")}
      </button>
    </form>
  );
}
