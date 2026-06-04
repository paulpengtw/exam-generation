import { useEffect, useMemo, useState } from "react";
import { getSchemas, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import CoreQuestionPicker from "./CoreQuestionPicker";

export interface GenerateParams {
  grade: number;
  style?: string;
  content_type?: string;
  context: string[];
  set_type: string;
  q_type: string[];
  count: number;
  skip_verify: boolean;
  image_generation_mode: "html" | "gpt_image";
  subject_filter?: string;
  passage?: string;
  options?: string[];
  topic?: string;
  core_question?: string;
  learning_performance?: string[];
}

export interface ParamFormProps {
  subject?: string;
  onSubmit: (params: GenerateParams) => void;
  disabled: boolean;
}

const TEXT_HINT = "500 字";
const OPTION_HINT = "50 字";
const SUBJECT_TO_PERFORMANCE_PREFIXES: Record<string, string[]> = {
  "": ["社"],
  "歷史": ["歷", "社"],
  "地理": ["地", "社"],
  "公民與社會": ["公", "社"],
  "跨科": ["歷", "地", "公", "社"],
};
const MATH_SUBJECT_TO_PERFORMANCE_PREFIXES: Record<string, string[]> = {
  "": ["n", "N", "r", "R", "a", "A", "f", "F", "s", "S", "g", "G", "d", "D", "p", "P"],
  "數與量": ["n", "N"],
  "代數": ["r", "R", "a", "A", "f", "F"],
  "幾何": ["s", "S", "g", "G"],
  "統計與機率": ["d", "D", "p", "P"],
};

export default function ParamForm({ subject = "math", onSubmit, disabled }: ParamFormProps) {
  const t = useT();
  const [schemas, setSchemas] = useState<Schemas | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [grade, setGrade] = useState<number | "">("");
  const [style, setStyle] = useState<string>("");
  const [contentType, setContentType] = useState<string>("純文字");
  const [customContentType, setCustomContentType] = useState<string>("");
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
  const [learningPerformance, setLearningPerformance] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    setSchemas(null);
    setError(null);
    setContext([]);
    setQType([]);
    setImageGenerationMode("html");
    setPassage(TEXT_HINT);
    setOptions([OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]);
    setSubjectFilter("");
    setLearningPerformance([]);
    getSchemas(subject)
      .then((s) => {
        if (cancelled) return;
        setSchemas(s);
        if (s.grades.length > 0) setGrade(s.grades[0]);
        const questionStyles = s.question_style ?? [];
        if (subject === "math" && questionStyles.length > 0) {
          setStyle(questionStyles[0].value);
        } else {
          setStyle("");
        }
        const contentTypes = s.題目內容類型 as Schemas["題目內容類型"] | undefined;
        setContentType(
          (subject === "social_studies" || subject === "math") &&
            Array.isArray(contentTypes) &&
            contentTypes.length > 0
            ? contentTypes[0].value
            : "純文字",
        );
        setCustomContentType("");
        if (s.題型種類.length > 0) setSetType(s.題型種類[0].value);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [subject]);

  const availableLearningPerformance = useMemo(() => {
    const entries = schemas?.學習表現 ?? [];
    const map =
      subject === "math" ? MATH_SUBJECT_TO_PERFORMANCE_PREFIXES : SUBJECT_TO_PERFORMANCE_PREFIXES;
    const prefixes = map[subjectFilter] ?? map[""];
    return entries.filter((entry) => prefixes.includes(entry.科目));
  }, [schemas, subjectFilter, subject]);

  useEffect(() => {
    const allowed = new Set(availableLearningPerformance.map((entry) => entry.value));
    setLearningPerformance((prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningPerformance]);

  function toggleMulti(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (grade === "") return;
    const cleanPassage = passage === TEXT_HINT ? undefined : passage;
    const cleanOptions = options.filter((o) => o && o !== OPTION_HINT);
    const cleanTopic = topic.trim();
    const effectiveContentType =
      subject === "social_studies" || subject === "math"
        ? (contentType === "customized" ? customContentType.trim() : contentType)
        : undefined;
    if ((subject === "social_studies" || subject === "math") && !effectiveContentType) return;
    onSubmit({
      grade,
      style: subject === "math" ? style : undefined,
      content_type: effectiveContentType,
      context,
      set_type: setType,
      q_type: qType,
      count,
      skip_verify: skipVerify,
      image_generation_mode: imageGenerationMode,
      subject_filter: subjectFilter || undefined,
      passage: cleanPassage,
      options: cleanOptions.length ? cleanOptions : undefined,
      topic:
        (subject === "social_studies" || subject === "math") && cleanTopic
          ? cleanTopic
          : undefined,
      core_question: coreQuestion || undefined,
      learning_performance:
        (subject === "social_studies" || subject === "math") && learningPerformance.length > 0
          ? learningPerformance
          : undefined,
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
      {(subject === "social_studies" || subject === "math") && (
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
              subject={subject}
              subjectFilter={subjectFilter || undefined}
              grade={grade !== "" ? grade : undefined}
              onPick={(q) => setCoreQuestion(q)}
              onClear={() => setCoreQuestion(null)}
              pickedValue={coreQuestion}
            />
          )}
        </div>
      )}

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

      {schemas.科目 && schemas.科目.length > 0 && (
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

      {Array.isArray(schemas.學習表現) && schemas.學習表現.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium">{t("form.learning_performance")}</legend>
          {availableLearningPerformance.length > 0 ? (
            <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {availableLearningPerformance.map((entry) => (
                <label key={entry.value} className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={learningPerformance.includes(entry.value)}
                    onChange={() =>
                      setLearningPerformance((prev) => toggleMulti(prev, entry.value))
                    }
                    className="mt-1"
                  />
                  <span className="text-sm">
                    <span className="font-medium">{entry.value}</span>
                    {entry.instruction && (
                      <span className="text-gray-600">：{entry.instruction}</span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-sm text-gray-500">{t("form.learning_performance_empty")}</p>
          )}
        </fieldset>
      )}

      {subject === "math" && (
        <div>
          <label className="block text-sm font-medium">{t("form.style")}</label>
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            {(schemas.question_style ?? []).map((s) => (
              <option key={s.value} value={s.value}>
                {s.value}
              </option>
            ))}
          </select>
        </div>
      )}

      {(subject === "social_studies" || subject === "math") && Array.isArray(schemas.題目內容類型) && (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{t("form.content_type")}</label>
          <select
            value={contentType}
            onChange={(e) => setContentType(e.target.value)}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            {schemas.題目內容類型.map((s) => (
              <option key={s.value} value={s.value}>
                {s.value === "customized" ? t("form.content_type_customized") : s.value}
              </option>
            ))}
          </select>
          {contentType === "customized" && (
            <input
              type="text"
              value={customContentType}
              onChange={(e) => setCustomContentType(e.target.value)}
              placeholder={t("form.content_type_custom_placeholder")}
              required
              className="block w-full border rounded px-2 py-1"
            />
          )}
        </div>
      )}

      {subject === "math" && (
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
      )}

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
        <label className="block text-sm font-medium">文本字數限制</label>
        <input
          type="text"
          value={passage}
          onFocus={() => { if (passage === TEXT_HINT) setPassage(""); }}
          onBlur={() => { if (passage === "") setPassage(TEXT_HINT); }}
          onChange={(e) => setPassage(e.target.value)}
          className="mt-1 block w-full border rounded px-2 py-1"
        />
      </div>

      <fieldset>
        <legend className="text-sm font-medium">選項字數限制</legend>
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

      {(subject === "social_studies" || subject === "math") && (
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

      {(subject === "social_studies" || subject === "math") && topic.trim() && !coreQuestion && (
        <p role="status" className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          ⚠ {t("form.topic_no_pick_warning")}
        </p>
      )}

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
