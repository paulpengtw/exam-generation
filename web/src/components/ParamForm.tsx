import { useEffect, useMemo, useState } from "react";
import { getSchemas, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import CoreQuestionPicker from "./CoreQuestionPicker";

export interface SubQuestionConfig {
  question_type?: string;
  instruction?: string;
  content_type?: string;
  image_generation_mode?: "html" | "gpt_image";
  question_word_limit?: number;
  option_word_limit?: number;
  text_word_limit?: number;
  learning_content?: string[];
  learning_performance?: string[];
}

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
  sub_context?: string;
  science_competency?: string[];
  learning_performance?: string[];
  learning_content?: string[];
  sub_question_count?: number;
  subquestion_configs?: string;
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
const SS_SUBJECT_FILTER_TO_CONTENT_CODE: Record<string, string | null> = {
  "": null,
  "歷史": "歷",
  "地理": "地",
  "公民與社會": "公",
  "跨科": null,
};

interface SearchPickerEntry {
  value: string;
  instruction?: string;
  科目?: string;
}

function SearchPicker({
  available,
  selected,
  onChange,
  placeholder,
}: {
  available: SearchPickerEntry[];
  selected: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return available
      .filter((item) => !selected.includes(item.value))
      .filter(
        (item) =>
          item.value.toLowerCase().includes(q) ||
          (item.instruction ?? "").toLowerCase().includes(q),
      )
      .slice(0, 10);
  }, [available, selected, query]);

  function handleSelect(value: string) {
    onChange([...selected, value]);
    setQuery("");
    setOpen(false);
  }

  function handleRemove(value: string) {
    onChange(selected.filter((v) => v !== value));
  }

  return (
    <div className="relative">
      <input
        type="text"
        value={query}
        autoComplete="off"
        placeholder={placeholder ?? "搜尋..."}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => { if (query) setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="block w-full border rounded px-2 py-1 text-sm"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-10 mt-0.5 w-full rounded border border-gray-200 bg-white shadow-md max-h-48 overflow-y-auto">
          {filtered.map((item) => (
            <button
              key={item.value}
              type="button"
              onMouseDown={() => handleSelect(item.value)}
              className="block w-full px-2 py-1.5 text-left text-xs hover:bg-gray-100"
            >
              <span className="font-medium">{item.value}</span>
              {item.instruction && (
                <span className="ml-1 text-gray-500">：{item.instruction}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {selected.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {selected.map((code) => {
            const item = available.find((a) => a.value === code);
            return (
              <span
                key={code}
                className="inline-flex items-center gap-0.5 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700 border border-blue-200"
              >
                <span className="font-medium">{code}</span>
                {item?.instruction && (
                  <span className="text-blue-500">
                    ：{item.instruction.length > 20 ? item.instruction.slice(0, 20) + "…" : item.instruction}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => handleRemove(code)}
                  className="ml-0.5 text-blue-400 hover:text-blue-600"
                >
                  ×
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ParamForm({ subject = "math", onSubmit, disabled }: ParamFormProps) {
  const t = useT();
  const [schemas, setSchemas] = useState<Schemas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingParams, setPendingParams] = useState<GenerateParams | null>(null);
  const [lpWasAutoDrawn, setLpWasAutoDrawn] = useState(false);
  const [lcWasAutoDrawn, setLcWasAutoDrawn] = useState(false);

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
  const [subContext, setSubContext] = useState<string>("");
  const [scienceCompetency, setScienceCompetency] = useState<string[]>([]);
  const [learningPerformance, setLearningPerformance] = useState<string[]>([]);
  const [learningContent, setLearningContent] = useState<string[]>([]);
  const [useCurriculumSearch, setUseCurriculumSearch] = useState<boolean>(false);
  const [subQuestionCount, setSubQuestionCount] = useState<number | "">("");
  const [subquestionConfigs, setSubquestionConfigs] = useState<SubQuestionConfig[]>([]);
  const isCurriculumSubject =
    subject === "social_studies" || subject === "math" || subject === "natural_sciences";

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
    setSubContext("");
    setScienceCompetency([]);
    setLearningPerformance([]);
    setLearningContent([]);
    setSubQuestionCount("");
    setSubquestionConfigs([]);
    getSchemas(subject)
      .then((s) => {
        if (cancelled) return;
        setSchemas(s);
        if (s.grades.length > 0) setGrade(s.grades[0]);
        if (subject === "natural_sciences" && s.情境.length > 0) {
          setContext([s.情境[0].value]);
          const firstSub = (s.情境子類別 ?? []).find(
            (entry) => entry.parent === s.情境[0].value,
          );
          setSubContext(firstSub?.value ?? "");
        }
        const questionStyles = s.question_style ?? [];
        if (subject === "math" && questionStyles.length > 0) {
          setStyle(questionStyles[0].value);
        } else {
          setStyle("");
        }
        const contentTypes = s.題目內容類型 as Schemas["題目內容類型"] | undefined;
        setContentType(
          isCurriculumSubject &&
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
  }, [subject, isCurriculumSubject]);

  // Re-fetch grade-dependent fields when grade changes so the correct learning stage is used.
  useEffect(() => {
    if (grade === "") return;
    let cancelled = false;
    getSchemas(subject, grade)
      .then((s) => {
        if (cancelled) return;
        setSchemas((prev) => prev ? { ...prev, 學習表現: s.學習表現, 學習內容: s.學習內容, 科目: s.科目 } : prev);
      })
      .catch(() => {/* non-critical — keep existing list */});
    return () => { cancelled = true; };
  }, [subject, grade]);

  const availableLearningPerformance = useMemo(() => {
    const entries = schemas?.學習表現 ?? [];
    if (subject === "natural_sciences") return entries;
    const map =
      subject === "math" ? MATH_SUBJECT_TO_PERFORMANCE_PREFIXES : SUBJECT_TO_PERFORMANCE_PREFIXES;
    const prefixes = map[subjectFilter] ?? map[""];
    return entries.filter((entry) => prefixes.includes(entry.科目));
  }, [schemas, subjectFilter, subject]);

  const availableSubContexts = useMemo(() => {
    const entries = schemas?.情境子類別 ?? [];
    const selectedContext = context[0] ?? "";
    return entries.filter((entry) => !entry.parent || entry.parent === selectedContext);
  }, [schemas, context]);

  const availableLearningContent = useMemo(() => {
    const entries = schemas?.學習內容 ?? [];
    if (subject === "social_studies") {
      if (!subjectFilter) return entries;
      const code = SS_SUBJECT_FILTER_TO_CONTENT_CODE[subjectFilter] ?? null;
      if (code === null) return entries;
      return entries.filter((e) => e.科目 === code);
    }
    if (subject === "natural_sciences") {
      if (!subjectFilter) return entries;
      return entries.filter((e) => !e.科目 || e.科目 === subjectFilter);
    }
    return entries;
  }, [schemas, subjectFilter, subject]);

  useEffect(() => {
    if (subject !== "natural_sciences") return;
    const allowed = new Set(availableSubContexts.map((entry) => entry.value));
    if (!subContext || !allowed.has(subContext)) {
      setSubContext(availableSubContexts[0]?.value ?? "");
    }
  }, [availableSubContexts, subContext, subject]);

  useEffect(() => {
    const allowed = new Set(availableLearningPerformance.map((entry) => entry.value));
    setLearningPerformance((prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningPerformance]);

  useEffect(() => {
    const allowed = new Set(availableLearningContent.map((entry) => entry.value));
    setLearningContent((prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningContent]);

  // Sync per-subquestion config rows with the selected count.
  useEffect(() => {
    const n = typeof subQuestionCount === "number" ? subQuestionCount : 0;
    setSubquestionConfigs((prev) => {
      if (n <= 0) return [];
      if (prev.length === n) return prev;
      if (prev.length < n) return [...prev, ...Array(n - prev.length).fill({})];
      return prev.slice(0, n);
    });
  }, [subQuestionCount]);

  function updateSubquestionConfig(index: number, patch: Partial<SubQuestionConfig>) {
    setSubquestionConfigs((prev) => prev.map((cfg, i) => i === index ? { ...cfg, ...patch } : cfg));
  }

  function optionalNumber(raw: string): number | undefined {
    if (raw.trim() === "") return undefined;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

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
      isCurriculumSubject
        ? (contentType === "customized" ? customContentType.trim() : contentType)
        : undefined;
    if (isCurriculumSubject && !effectiveContentType) return;
    const effectiveSubquestionConfigs =
      (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== ""
        ? subquestionConfigs.slice(0, subQuestionCount).map((cfg) => ({
            question_type: cfg.question_type || undefined,
            instruction: cfg.instruction?.trim() || undefined,
            content_type: cfg.content_type || undefined,
            image_generation_mode: cfg.image_generation_mode || undefined,
            question_word_limit: cfg.question_word_limit,
            option_word_limit: cfg.option_word_limit,
            text_word_limit: cfg.text_word_limit,
            learning_content: cfg.learning_content?.length ? cfg.learning_content : undefined,
            learning_performance: cfg.learning_performance?.length ? cfg.learning_performance : undefined,
          }))
        : [];
    const hasSubquestionConfig = effectiveSubquestionConfigs.some(
      (c) => c.question_type || c.instruction || c.content_type || c.image_generation_mode || c.question_word_limit || c.option_word_limit || c.text_word_limit || c.learning_content?.length || c.learning_performance?.length,
    );
    const shouldSendSubquestionConfigs =
      (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== "" && (
        hasSubquestionConfig || effectiveSubquestionConfigs.length > 0
      );

    // If no learning_performance selected, pre-draw randomly to match backend sampling
    let finalLp: string[] | undefined;
    let autoDrawn = false;
    if (isCurriculumSubject && learningPerformance.length === 0 && availableLearningPerformance.length > 0) {
      const maxDraw = subject === "math" ? 3 : 2;
      const drawCount = Math.floor(Math.random() * Math.min(maxDraw, availableLearningPerformance.length)) + 1;
      const shuffled = [...availableLearningPerformance].sort(() => Math.random() - 0.5);
      finalLp = shuffled.slice(0, drawCount).map((e) => e.value);
      autoDrawn = true;
    } else if (isCurriculumSubject && learningPerformance.length > 0) {
      finalLp = learningPerformance;
    }

    setLpWasAutoDrawn(autoDrawn);
    let finalLc: string[] | undefined;
    let lcAutoDrawn = false;
    if (
      (subject === "natural_sciences" || subject === "social_studies") &&
      learningContent.length === 0 &&
      availableLearningContent.length > 0
    ) {
      const drawCount = Math.floor(Math.random() * Math.min(3, availableLearningContent.length)) + 1;
      const shuffled = [...availableLearningContent].sort(() => Math.random() - 0.5);
      finalLc = shuffled.slice(0, drawCount).map((e) => e.value);
      lcAutoDrawn = true;
    } else if (
      (subject === "natural_sciences" || subject === "social_studies") &&
      learningContent.length > 0
    ) {
      finalLc = learningContent;
    }

    setLcWasAutoDrawn(lcAutoDrawn);
    setPendingParams({
      grade,
      style: subject === "math" ? style : undefined,
      content_type: effectiveContentType,
      context: subject === "natural_sciences" ? context.slice(0, 1) : context,
      set_type: setType,
      q_type: subject === "social_studies" ? [] : qType,
      count,
      skip_verify: skipVerify,
      image_generation_mode: imageGenerationMode,
      subject_filter: subjectFilter || undefined,
      passage: cleanPassage,
      options: subject === "math" && cleanOptions.length ? cleanOptions : undefined,
      topic:
        isCurriculumSubject && cleanTopic
          ? cleanTopic
          : undefined,
      core_question: coreQuestion || undefined,
      learning_performance: finalLp,
      sub_context: subject === "natural_sciences" ? subContext : undefined,
      science_competency:
        subject === "natural_sciences" && scienceCompetency.length > 0
          ? scienceCompetency
          : undefined,
      learning_content:
        finalLc,
      sub_question_count: (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== "" ? subQuestionCount : undefined,
      subquestion_configs:
        shouldSendSubquestionConfigs
          ? JSON.stringify(effectiveSubquestionConfigs)
          : undefined,
    });
  }

  function handleConfirmSend() {
    if (!pendingParams) return;
    setPendingParams(null);
    onSubmit(pendingParams);
  }

  if (pendingParams) {
    const p = pendingParams;

    // Resolve full 學習表現 entries for display
    const allLpEntries = schemas?.學習表現 ?? [];
    const lpDisplayEntries = p.learning_performance
      ? allLpEntries.filter((e) => p.learning_performance!.includes(e.value))
      : [];

    // Resolve full 學習內容 entries for display
    const allLcEntries = schemas?.學習內容 ?? [];
    const lcDisplayEntries = p.learning_content
      ? allLcEntries.filter((e) => p.learning_content!.includes(e.value))
      : [];

    const rows: { label: string; value: string | undefined }[] = [
      { label: t("form.confirm_topic"), value: p.topic },
      { label: t("form.confirm_core_question"), value: p.core_question },
      { label: t("form.confirm_grade"), value: String(p.grade) },
      { label: t("form.confirm_subject_filter"), value: p.subject_filter },
      { label: t("form.confirm_style"), value: p.style },
      { label: t("form.confirm_content_type"), value: p.content_type },
      { label: t("form.confirm_context"), value: p.context.length ? p.context.join(", ") : undefined },
      { label: t("form.confirm_set_type"), value: p.set_type },
      {
        label: t("form.confirm_q_type"),
        value: subject !== "social_studies" && p.q_type.length ? p.q_type.join(", ") : undefined,
      },
      { label: t("form.confirm_count"), value: String(p.count) },
      { label: t("form.confirm_passage"), value: p.passage },
      { label: t("form.confirm_options"), value: p.options?.join(", ") },
      {
        label: t("form.confirm_image_mode"),
        value: p.image_generation_mode,
      },
      { label: t("form.confirm_skip_verify"), value: p.skip_verify ? "✓" : undefined },
      { label: "小題數量", value: p.sub_question_count !== undefined ? String(p.sub_question_count) : undefined },
      { label: "各小題配置", value: p.subquestion_configs },
    ];

    const lpHeading = lpWasAutoDrawn
      ? t("form.confirm_lp_random_pool").replace("{n}", String(lpDisplayEntries.length))
      : t("form.confirm_lp_selected").replace("{n}", String(lpDisplayEntries.length));
    const lcHeading = lcWasAutoDrawn
      ? t("form.confirm_lc_random_pool").replace("{n}", String(lcDisplayEntries.length))
      : t("form.confirm_lc_selected").replace("{n}", String(lcDisplayEntries.length));

    return (
      <div className="space-y-4">
        <div>
          <h2 className="text-base font-semibold">{t("form.confirm_title")}</h2>
          <p className="mt-1 text-sm text-gray-500">{t("form.confirm_subtitle")}</p>
        </div>
        <dl className="divide-y rounded-lg border bg-gray-50">
          {rows.map(({ label, value }) => (
            <div key={label} className="flex gap-3 px-4 py-2.5">
              <dt className="w-40 shrink-0 text-sm font-medium text-gray-600">{label}</dt>
              <dd className="flex-1 text-sm text-gray-900 break-words">
                {value ?? <span className="text-gray-400 italic">{t("form.confirm_none")}</span>}
              </dd>
            </div>
          ))}
          <div className="flex gap-3 px-4 py-2.5">
            <dt className="w-40 shrink-0 text-sm font-medium text-gray-600">{t("form.confirm_learning_performance")}</dt>
            <dd className="flex-1 text-sm text-gray-900">
              {lpDisplayEntries.length === 0 ? (
                <span className="text-gray-400 italic">{t("form.confirm_none")}</span>
              ) : (
                <div className="space-y-1">
                  <p className={`text-xs font-medium mb-1.5 ${lpWasAutoDrawn ? "text-amber-700" : "text-green-700"}`}>
                    {lpHeading}
                  </p>
                  <ul className="space-y-1">
                    {lpDisplayEntries.map((entry) => (
                      <li key={entry.value} className="flex gap-2 text-sm">
                        <span className="shrink-0 font-mono font-semibold text-gray-800">{entry.value}</span>
                        {entry.instruction && (
                          <span className="text-gray-600">— {entry.instruction}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </dd>
          </div>
          <div className="flex gap-3 px-4 py-2.5">
            <dt className="w-40 shrink-0 text-sm font-medium text-gray-600">{t("form.confirm_learning_content")}</dt>
            <dd className="flex-1 text-sm text-gray-900">
              {lcDisplayEntries.length === 0 ? (
                <span className="text-gray-400 italic">{t("form.confirm_none")}</span>
              ) : (
                <div className="space-y-1">
                  <p className={`text-xs font-medium mb-1.5 ${lcWasAutoDrawn ? "text-amber-700" : "text-green-700"}`}>
                    {lcHeading}
                  </p>
                  <ul className="space-y-1">
                    {lcDisplayEntries.map((entry) => (
                      <li key={entry.value} className="flex gap-2 text-sm">
                        <span className="shrink-0 font-mono font-semibold text-gray-800">{entry.value}</span>
                        {entry.instruction && (
                          <span className="text-gray-600">— {entry.instruction}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-3 pt-1">
          <button
            type="button"
            onClick={handleConfirmSend}
            disabled={disabled}
            className="inline-flex items-center gap-2 rounded bg-blue-600 px-5 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("form.btn_confirm_send")}
          </button>
          <button
            type="button"
            onClick={() => setPendingParams(null)}
            className="rounded border border-gray-300 bg-white px-4 py-2 font-medium text-gray-700 hover:bg-gray-50"
          >
            {t("form.btn_back_edit")}
          </button>
        </div>
      </div>
    );
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
      {isCurriculumSubject && (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{t("form.topic_label")}</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setCoreQuestion(null);
            }}
            onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
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
        <div>
          <div className="flex items-center justify-between">
            <label className="block text-sm font-medium">{t("form.learning_performance")}</label>
            <button
              type="button"
              onClick={() => setUseCurriculumSearch((v) => !v)}
              className="text-xs text-blue-600 hover:underline"
            >
              {useCurriculumSearch ? "切換勾選模式" : "切換搜尋模式"}
            </button>
          </div>
          {availableLearningPerformance.length > 0 ? (
            useCurriculumSearch ? (
              <div className="mt-1">
                <SearchPicker
                  available={availableLearningPerformance}
                  selected={learningPerformance}
                  onChange={setLearningPerformance}
                  placeholder="搜尋學習表現..."
                />
              </div>
            ) : (
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
            )
          ) : (
            <p className="mt-1 text-sm text-gray-500">{t("form.learning_performance_empty")}</p>
          )}
        </div>
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

      {isCurriculumSubject && Array.isArray(schemas.題目內容類型) && (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{subject === "social_studies" ? "文本素材類型" : t("form.content_type")}</label>
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

      {isCurriculumSubject && (
        <div>
          <label className="block text-sm font-medium">
            {subject === "social_studies" ? "圖片生成模式" : t("form.image_generation_mode")}
          </label>
          <select
            value={imageGenerationMode}
            onChange={(e) =>
              setImageGenerationMode(e.target.value as "html" | "gpt_image")
            }
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="html">
              {subject === "social_studies" ? "HTML 渲染" : t("form.image_generation_mode_html")}
            </option>
            <option value="gpt_image">
              {subject === "social_studies" ? "GPT 生圖" : t("form.image_generation_mode_gpt")}
            </option>
          </select>
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

      {subject === "natural_sciences" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium">{t("form.context")}</label>
            <select
              value={context[0] ?? ""}
              onChange={(e) => setContext(e.target.value ? [e.target.value] : [])}
              className="mt-1 block w-full border rounded px-2 py-1"
            >
              {schemas.情境.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.value}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">{t("form.sub_context")}</label>
            <select
              value={subContext}
              onChange={(e) => setSubContext(e.target.value)}
              className="mt-1 block w-full border rounded px-2 py-1"
            >
              {availableSubContexts.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.value}
                </option>
              ))}
            </select>
          </div>
        </div>
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

      {subject !== "social_studies" && (
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
      )}

      {subject === "natural_sciences" && Array.isArray(schemas.科學能力) && (
        <fieldset>
          <legend className="text-sm font-medium">{t("form.science_competency")}</legend>
          <div className="mt-1 grid grid-cols-1 gap-2">
            {schemas.科學能力.map((s) => (
              <label key={s.value} className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={scienceCompetency.includes(s.value)}
                  onChange={() =>
                    setScienceCompetency((prev) => toggleMulti(prev, s.value))
                  }
                  className="mt-1"
                />
                <span className="text-sm">
                  <span className="font-medium">{s.value}</span>
                  {s.instruction && (
                    <span className="text-gray-600">：{s.instruction}</span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {(subject === "natural_sciences" || subject === "social_studies") && Array.isArray(schemas.學習內容) && schemas.學習內容.length > 0 && (
        <div>
          <div className="flex items-center justify-between">
            <label className="block text-sm font-medium">{t("form.learning_content")}</label>
            <button
              type="button"
              onClick={() => setUseCurriculumSearch((v) => !v)}
              className="text-xs text-blue-600 hover:underline"
            >
              {useCurriculumSearch ? "切換勾選模式" : "切換搜尋模式"}
            </button>
          </div>
          {availableLearningContent.length > 0 ? (
            useCurriculumSearch ? (
              <div className="mt-1">
                <SearchPicker
                  available={availableLearningContent}
                  selected={learningContent}
                  onChange={setLearningContent}
                  placeholder="搜尋學習內容..."
                />
              </div>
            ) : (
              <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {availableLearningContent.map((entry) => (
                  <label key={entry.value} className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={learningContent.includes(entry.value)}
                      onChange={() =>
                        setLearningContent((prev) => toggleMulti(prev, entry.value))
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
            )
          ) : (
            <p className="mt-1 text-sm text-gray-500">{t("form.learning_content_empty")}</p>
          )}
        </div>
      )}

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

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <div className="space-y-4 rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700">子題設定</h3>
          <div className="max-w-40">
            <div>
              <label className="block text-sm font-medium">小題數量</label>
              <input
                type="number"
                min={3}
                max={7}
                value={subQuestionCount}
                onChange={(e) => {
                  const v = e.target.value;
                  setSubQuestionCount(v === "" ? "" : Math.min(7, Math.max(3, Number(v) || 3)));
                }}
                placeholder="自動 3-7"
                className="mt-1 block w-full border rounded px-2 py-1"
              />
            </div>
          </div>

          {subquestionConfigs.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-medium text-gray-600">各小題配置</h4>
              {subquestionConfigs.map((cfg, i) => (
                <div key={i} className="rounded border border-gray-100 bg-gray-50 px-3 py-2">
                  <span className="block text-sm font-medium text-gray-700">第{i + 1}小題</span>
                  <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-6">
                    <div>
                      <label className="block text-xs text-gray-500">題型</label>
                      <select
                        value={cfg.question_type ?? ""}
                        onChange={(e) => updateSubquestionConfig(i, { question_type: e.target.value || undefined })}
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      >
                        <option value="">（隨機）</option>
                        {schemas.題型.map((s) => (
                          <option key={s.value} value={s.value}>{s.value}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500">文本字數限制</label>
                      <input
                        type="number"
                        min={1}
                        value={cfg.text_word_limit ?? ""}
                        onChange={(e) =>
                          updateSubquestionConfig(i, {
                            text_word_limit: optionalNumber(e.target.value),
                          })
                        }
                        placeholder="不限"
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500">題目字數限制</label>
                      <input
                        type="number"
                        min={1}
                        value={cfg.question_word_limit ?? ""}
                        onChange={(e) =>
                          updateSubquestionConfig(i, {
                            question_word_limit: optionalNumber(e.target.value),
                          })
                        }
                        placeholder="不限"
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500">選項字數限制</label>
                      <input
                        type="number"
                        min={1}
                        value={cfg.option_word_limit ?? ""}
                        onChange={(e) =>
                          updateSubquestionConfig(i, {
                            option_word_limit: optionalNumber(e.target.value),
                          })
                        }
                        placeholder="選擇題適用"
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500">題目內容類型</label>
                      <select
                        value={cfg.content_type ?? ""}
                        onChange={(e) => updateSubquestionConfig(i, { content_type: e.target.value || undefined })}
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      >
                        <option value="">（沿用文本設定）</option>
                        {(schemas.題目內容類型 ?? []).map((s) => (
                          <option key={s.value} value={s.value}>{s.value}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500">圖片生成模式</label>
                      <select
                        value={cfg.image_generation_mode ?? ""}
                        onChange={(e) => updateSubquestionConfig(i, { image_generation_mode: (e.target.value as "html" | "gpt_image") || undefined })}
                        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                      >
                        <option value="">（沿用文本設定）</option>
                        <option value="html">HTML 渲染</option>
                        <option value="gpt_image">GPT 生圖</option>
                      </select>
                    </div>
                  </div>
                  <div className="mt-3">
                    <label className="block text-xs text-gray-500">出題指示</label>
                    <textarea
                      value={cfg.instruction ?? ""}
                      onChange={(e) => updateSubquestionConfig(i, { instruction: e.target.value || undefined })}
                      placeholder="例如：請聚焦在資料判讀與因果推論"
                      rows={2}
                      className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                    />
                  </div>
                  {(availableLearningPerformance.length > 0 || availableLearningContent.length > 0) && (
                    <div className="mt-3 space-y-2">
                      <p className="text-xs text-gray-500">留空 = 沿用全域設定</p>
                      {availableLearningPerformance.length > 0 && (
                        <div>
                          <p className="text-xs text-gray-500 mb-0.5">學習表現 (留空沿用全域)</p>
                          <SearchPicker
                            available={availableLearningPerformance}
                            selected={cfg.learning_performance ?? []}
                            onChange={(vals) =>
                              updateSubquestionConfig(i, { learning_performance: vals.length ? vals : undefined })
                            }
                            placeholder="搜尋學習表現..."
                          />
                        </div>
                      )}
                      {availableLearningContent.length > 0 && (
                        <div>
                          <p className="text-xs text-gray-500 mb-0.5">學習內容 (留空沿用全域)</p>
                          <SearchPicker
                            available={availableLearningContent}
                            selected={cfg.learning_content ?? []}
                            onChange={(vals) =>
                              updateSubquestionConfig(i, { learning_content: vals.length ? vals : undefined })
                            }
                            placeholder="搜尋學習內容..."
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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

      {subject === "math" && (
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
      )}

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={skipVerify}
          onChange={(e) => setSkipVerify(e.target.checked)}
        />
        <span className="text-sm">{t("form.skip_verify")}</span>
      </label>

      {isCurriculumSubject && topic.trim() && !coreQuestion && (
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
