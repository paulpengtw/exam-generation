import { useEffect, useMemo, useRef, useState } from "react";
import { getAvailableModels, getSchemas, planCoreQuestions, previewGenerate, type AvailableModels, type PromptPreview, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import { drawRandomSubset } from "../utils/drawRandomSubset";
import CoreQuestionPicker from "./CoreQuestionPicker";
import type { GenerateParams as WireGenerateParams } from "../api/generated/contract";
import { toGenerateParams } from "../utils/toGenerateParams";

export interface SubQuestionConfig {
  question_type?: string;
  instruction?: string;
  content_type?: string;
  image_generation_mode?: "html" | "gpt_image";
  question_word_limit?: number;
  option_word_limit?: number;
  text_word_limit?: number;
  reporting_scale?: string;
  learning_content?: string[];
  learning_performance?: string[];
}

type ResolvedSubQuestionConfig = SubQuestionConfig & {
  _lcWasAutoDrawn?: boolean;
  _lpWasAutoDrawn?: boolean;
};

function parseSubquestionConfigs(value: unknown): SubQuestionConfig[] {
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (row): row is SubQuestionConfig => typeof row === "object" && row !== null && !Array.isArray(row),
    );
  } catch {
    return [];
  }
}

/**
 * Form-specific param shape — collected from ParamForm and passed to
 * GeneratePage.handleSubmit, which bridges it to the wire GenerateParams.
 *
 * Inherits all optional wire fields unchanged (so adding a wire field
 * automatically makes it available here). Fields that the form treats
 * differently are listed in the intersection below with inline comments.
 */
export type FormParams = Omit<
  WireGenerateParams,
  // GeneratePage injects `subject` from its own props — not a form control.
  | "subject"
  // Not exposed in the form UI.
  | "seed"
  // Not exposed in the form UI.
  | "max_retries"
  // Not exposed in the form UI.
  | "core_competency"
  // Exposed per-subquestion inside subquestion_configs, not at top level.
  | "question_word_limit"
  // Exposed per-subquestion inside subquestion_configs, not at top level.
  | "option_word_limit"
  // Form sends a single string; GeneratePage wraps it in [style].
  | "style"
  // Form sends a single string; GeneratePage wraps it in [subject_filter].
  | "subject_filter"
  // Required in form — always provided before submit.
  | "grade"
  | "context"
  | "set_type"
  | "q_type"
  | "count"
  | "skip_verify"
  | "image_generation_mode"
> & {
  // Required: the form always has a grade selected before submit.
  grade: number;
  // Required: defaults to [] when no context is chosen.
  context: string[];
  // Required: always set from the schema dropdown.
  set_type: string;
  // Required: always set from the schema dropdown.
  q_type: string[];
  // Required: defaults to 1.
  count: number;
  // Required: defaults to false.
  skip_verify: boolean;
  // Required: defaults to "html".
  image_generation_mode: "html" | "gpt_image";
  // Form sends a single string; GeneratePage wraps it in [style] for the wire call.
  style?: string;
  // Form sends a single string; GeneratePage wraps it in [subject_filter] for the wire call.
  subject_filter?: string;
};

export interface ParamFormProps {
  subject?: string;
  onSubmit: (params: FormParams) => void;
  disabled: boolean;
  initialParams?: Partial<FormParams> & { [key: string]: unknown };
}

type ConfirmationValueKind = "absent" | "sampled" | "defaulted";

type ConfirmationRow = {
  label: string;
  value: string | undefined;
  subjects: string[];
  kind?: ConfirmationValueKind;
  defaultValue?: string;
  badge?: string;
};

function resolveConfirmationValue(
  value: string | undefined,
  kind: ConfirmationValueKind,
  t: (key: string) => string,
  defaultValue?: string,
) {
  if (value !== undefined && value !== "") return value;
  if (kind === "sampled") return t("form.confirm_backend_sampled");
  if (kind === "defaulted") return defaultValue ?? t("form.confirm_not_filled");
  return t("form.confirm_not_filled");
}

function drawQuestionSubset<T>(
  pool: readonly T[],
  min: number,
  max: number,
  previous?: readonly T[],
): T[] {
  const drawn = drawRandomSubset(pool, min, max);
  if (!previous || pool.length < 2 || JSON.stringify(drawn) !== JSON.stringify(previous)) {
    return drawn;
  }
  const alternative = pool.find((value) => !previous.includes(value));
  if (alternative !== undefined) return [alternative];
  return drawn.length > 1 ? [drawn[0]] : drawn;
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

export default function ParamForm({
  subject = "math",
  onSubmit,
  disabled,
  initialParams,
}: ParamFormProps) {
  const t = useT();
  const [schemas, setSchemas] = useState<Schemas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [pendingParams, setPendingParams] = useState<FormParams | null>(null);
  const [coreQuestionResolution, setCoreQuestionResolution] = useState<"idle" | "loading" | "generated" | "failed">("idle");
  const [lpWasAutoDrawn, setLpWasAutoDrawn] = useState(false);
  const [lcWasAutoDrawn, setLcWasAutoDrawn] = useState(false);
  const [pendingResolvedSubquestionConfigs, setPendingResolvedSubquestionConfigs] = useState<
    ResolvedSubQuestionConfig[]
  >([]);
  const [perQuestionAutoFields, setPerQuestionAutoFields] = useState<string[][]>([]);
  const [promptPreviews, setPromptPreviews] = useState<PromptPreview[]>([]);
  const previewRequestedRef = useRef(false);

  const ip = initialParams ?? {};
  const userChosenFields = useRef(new Set(Object.keys(ip)));
  function fromInit<T>(key: string, fallback: T): T {
    return (ip[key] as T | undefined) ?? fallback;
  }
  function markUserChosen(key: string) {
    userChosenFields.current.add(key);
  }

  const [grade, setGrade] = useState<number | "">(fromInit<number | "">("grade", ""));
  const [style, setStyle] = useState<string>(fromInit<string>("style", ""));
  const [contentType, setContentType] = useState<string>(
    fromInit<string>("content_type", "純文字"),
  );
  const [customContentType, setCustomContentType] = useState<string>("");
  const [context, setContext] = useState<string[]>(fromInit<string[]>("context", []));
  const [setType, setSetType] = useState<string>(fromInit<string>("set_type", ""));
  const [qType, setQType] = useState<string[]>(fromInit<string[]>("q_type", []));
  const [count, setCount] = useState<number>(fromInit<number>("count", 1));
  const configuredSeed = fromInit<number | undefined>("seed", undefined);
  const [coverageMode, setCoverageMode] = useState<"balanced" | "random">("balanced");
  const [skipVerify, setSkipVerify] = useState<boolean>(
    fromInit<boolean>("skip_verify", false),
  );
  const [disableReferenceFewshot, setDisableReferenceFewshot] =
    useState<boolean>(fromInit<boolean>("disable_reference_fewshot", false));
  const [imageGenerationMode, setImageGenerationMode] =
    useState<"html" | "gpt_image">(
      fromInit<"html" | "gpt_image">("image_generation_mode", "html"),
    );
  const [difficulty, setDifficulty] = useState<"" | "easy" | "medium" | "hard">(
    fromInit<"" | "easy" | "medium" | "hard">("difficulty", ""),
  );
  const [subjectFilter, setSubjectFilter] = useState<string>(
    (() => {
      const v = fromInit<string | string[]>("subject_filter", "");
      return Array.isArray(v) ? (v[0] ?? "") : v;
    })(),
  );
  const [passage, setPassage] = useState<string>(fromInit<string>("passage", TEXT_HINT));
  const [textWordLimit, setTextWordLimit] = useState<number | undefined>(
    fromInit<number | undefined>("text_word_limit", undefined),
  );
  const [options, setOptions] = useState<string[]>(
    fromInit<string[]>("options", [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]),
  );
  const [topic, setTopic] = useState<string>(fromInit<string>("topic", ""));
  const [coreQuestion, setCoreQuestion] = useState<string | null>(
    fromInit<string | null>("core_question", null),
  );
  const [subContext, setSubContext] = useState<string>(fromInit<string>("sub_context", ""));
  const [scienceCompetency, setScienceCompetency] = useState<string[]>(
    fromInit<string[]>("science_competency", []),
  );

  useEffect(() => {
    if (!pendingParams || coreQuestionResolution === "loading" || previewRequestedRef.current) return;
    let cancelled = false;
    previewRequestedRef.current = true;
    void previewGenerate(toGenerateParams(subject, pendingParams))
      .then(({ prompts }) => {
        if (cancelled) return;
        if (
          Array.isArray(prompts) &&
          prompts.every((prompt) => (
            Number.isInteger(prompt?.index) &&
            prompt.index >= 0 &&
            (
              prompt.subquestion_index === undefined ||
              (
                Number.isInteger(prompt.subquestion_index) &&
                prompt.subquestion_index >= 0
              )
            ) &&
            typeof prompt?.system_prompt === "string" &&
            typeof prompt?.user_prompt === "string"
          ))
        ) {
          setPromptPreviews(prompts);
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [coreQuestionResolution, pendingParams, subject]);

  useEffect(() => {
    if (!pendingParams || coreQuestionResolution !== "loading") return;
    let cancelled = false;
    void planCoreQuestions({
      topic: pendingParams.topic ?? "",
      subject,
      subject_filter: pendingParams.subject_filter ? [pendingParams.subject_filter] : undefined,
      grade: pendingParams.grade,
    }).then(({ candidates }) => {
      if (cancelled) return;
      if (candidates.length === 0) {
        setCoreQuestionResolution("failed");
        return;
      }
      const selected = candidates[Math.floor(Math.random() * candidates.length)];
      setPendingParams((current) => {
        if (!current) return current;
        const perQuestion = current.per_question_params
          ? (JSON.parse(current.per_question_params) as Record<string, unknown>[]).map((item) => ({
              ...item,
              core_question: selected,
            }))
          : undefined;
        return {
          ...current,
          core_question: selected,
          per_question_params: perQuestion ? JSON.stringify(perQuestion) : undefined,
        };
      });
      setCoreQuestionResolution("generated");
    }).catch(() => {
      if (cancelled) return;
      setCoreQuestionResolution("failed");
    });
    return () => { cancelled = true; };
  }, [coreQuestionResolution, pendingParams, subject]);
  const [learningPerformance, setLearningPerformance] = useState<string[]>(
    fromInit<string[]>("learning_performance", []),
  );
  const [learningContent, setLearningContent] = useState<string[]>(
    fromInit<string[]>("learning_content", []),
  );
  const [useCurriculumSearch, setUseCurriculumSearch] = useState<boolean>(false);
  const [subQuestionCount, setSubQuestionCount] = useState<number | "">(
    fromInit<number | "">("sub_question_count", ""),
  );
  const [subquestionConfigs, setSubquestionConfigs] = useState<SubQuestionConfig[]>(
    fromInit<SubQuestionConfig[]>("subquestion_configs", []),
  );
  const [models, setModels] = useState<AvailableModels | null>(null);
  const [modelPlan, setModelPlan] = useState<string>(
    () => window.localStorage.getItem("model_plan") ?? "",
  );
  const [modelExecute, setModelExecute] = useState<string>(
    () => window.localStorage.getItem("model_execute") ?? "",
  );
  const isCurriculumSubject =
    subject === "social_studies" || subject === "math" || subject === "natural_sciences";
  const supportsTextWordLimit = isCurriculumSubject && subject !== "math";

  useEffect(() => {
    let cancelled = false;
    setSchemas(null);
    setError(null);
    setContext(fromInit<string[]>("context", []));
    setQType(fromInit<string[]>("q_type", []));
    setImageGenerationMode(
      fromInit<"html" | "gpt_image">("image_generation_mode", "html"),
    );
    setDifficulty(fromInit<"" | "easy" | "medium" | "hard">("difficulty", ""));
    setPassage(fromInit<string>("passage", TEXT_HINT));
    setTextWordLimit(fromInit<number | undefined>("text_word_limit", undefined));
    setOptions(
      fromInit<string[]>("options", [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]),
    );
    setSubjectFilter(
      (() => {
        const v = fromInit<string | string[]>("subject_filter", "");
        return Array.isArray(v) ? (v[0] ?? "") : v;
      })(),
    );
    setSubContext(fromInit<string>("sub_context", ""));
    setScienceCompetency(fromInit<string[]>("science_competency", []));
    setLearningPerformance(fromInit<string[]>("learning_performance", []));
    setLearningContent(fromInit<string[]>("learning_content", []));
    setSubQuestionCount(fromInit<number | "">("sub_question_count", ""));
    setSubquestionConfigs(fromInit<SubQuestionConfig[]>("subquestion_configs", []));
    setTopic(fromInit<string>("topic", ""));
    setCoreQuestion(fromInit<string | null>("core_question", null));
    getSchemas(subject)
      .then((s) => {
        if (cancelled) return;
        setSchemas(s);
        if (s.grades.length > 0 && ip.grade === undefined) setGrade(s.grades[0]);
        if (
          subject === "natural_sciences" &&
          s.情境.length > 0 &&
          ip.sub_context === undefined
        ) {
          setContext([s.情境[0].value]);
          const firstSub = (s.情境子類別 ?? []).find(
            (entry) => entry.parent === s.情境[0].value,
          );
          setSubContext(firstSub?.value ?? "");
        }
        const questionStyles = s.question_style ?? [];
        if (ip.style === undefined) {
          if (subject === "math" && questionStyles.length > 0) {
            setStyle(questionStyles[0].value);
          } else {
            setStyle("");
          }
        }
        if (ip.content_type === undefined) {
          const contentTypes = s.題目內容類型 as Schemas["題目內容類型"] | undefined;
          setContentType(
            isCurriculumSubject &&
              Array.isArray(contentTypes) &&
              contentTypes.length > 0
              ? contentTypes[0].value
              : "純文字",
          );
        }
        setCustomContentType("");
        if (s.題型種類.length > 0 && ip.set_type === undefined) setSetType(s.題型種類[0].value);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initialParams intentionally only applied on mount/subject change, not re-run per keystroke
  }, [subject, isCurriculumSubject]);

  useEffect(() => {
    let cancelled = false;
    getAvailableModels()
      .then((m) => {
        if (cancelled) return;
        setModels(m);
        // Reconcile any localStorage-hydrated selection against the live
        // allowlist — a stale value (e.g. a model that was removed server
        // side) must never be silently submitted.
        const allowed = new Set(m.allowed);
        setModelPlan((prev) => (prev && !allowed.has(prev) ? "" : prev));
        setModelExecute((prev) => (prev && !allowed.has(prev) ? "" : prev));
      })
      .catch(() => {
        if (cancelled) return;
        // Discovery failure: hide the dropdowns AND clear any selection —
        // the binding is that no model_plan/model_execute is ever sent
        // when /api/models fails, even for a returning user with a
        // persisted choice.
        setModels(null);
        setModelPlan("");
        setModelExecute("");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem("model_plan", modelPlan);
  }, [modelPlan]);
  useEffect(() => {
    window.localStorage.setItem("model_execute", modelExecute);
  }, [modelExecute]);

  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);
  useEffect(() => {
    if (!schemas || !initialParams) return;
    const missing: string[] = [];
    const arr = (key: string): string[] => {
      const raw = (initialParams as Record<string, unknown>)[key];
      return Array.isArray(raw) ? (raw as string[]) : [];
    };
    const single = (key: string): string | undefined => {
      const raw = (initialParams as Record<string, unknown>)[key];
      return typeof raw === "string" ? raw : undefined;
    };
    const check = (
      key: string,
      values: string[],
      allowed: string[] | undefined,
    ): void => {
      if (!allowed) return;
      for (const v of values) if (!allowed.includes(v)) missing.push(`${key}: ${v}`);
    };
    check("情境", arr("context"), schemas.情境?.map((s) => s.value));
    check("題型", arr("q_type"), schemas.題型?.map((s) => s.value));
    const st = single("set_type");
    if (st !== undefined) {
      check("題型種類", [st], schemas.題型種類?.map((s) => s.value));
    }
    check(
      "科目",
      arr("subject_filter"),
      schemas.科目?.map((s) => s.value),
    );
    if (missing.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reconciling initialParams against freshly-loaded schemas, matches existing HistoryPage/VerifyPage pattern
      setPrefillNotice(t("history.prefill_notice"));
      // Drop the missing entries so the form submits a clean payload.
      const allowedCtx = new Set(schemas.情境?.map((s) => s.value));
      setContext((prev) => prev.filter((v) => allowedCtx.has(v)));
      const allowedQT = new Set(schemas.題型?.map((s) => s.value));
      setQType((prev) => prev.filter((v) => allowedQT.has(v)));
      const allowedST = new Set(schemas.題型種類?.map((s) => s.value));
      setSetType((prev) => (allowedST.has(prev) ? prev : ""));
    } else {
      setPrefillNotice(null);
    }
  }, [schemas, initialParams, t]);

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
    if (!schemas) return;
    const allowed = new Set(availableLearningPerformance.map((entry) => entry.value));
    setLearningPerformance((prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningPerformance, schemas]);

  useEffect(() => {
    if (!schemas) return;
    const allowed = new Set(availableLearningContent.map((entry) => entry.value));
    setLearningContent((prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningContent, schemas]);

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
    previewRequestedRef.current = false;
    setPromptPreviews([]);
    if (grade === "") return;
    if (!setType.trim()) {
      setValidationError(t("form.error_set_type_required"));
      return;
    }
    setValidationError(null);
    const cleanPassage = passage === TEXT_HINT ? undefined : passage;
    const cleanOptions = options.filter((o) => o && o !== OPTION_HINT);
    const cleanTopic = topic.trim();
    const effectiveContentType =
      isCurriculumSubject
        ? (contentType === "customized" ? customContentType.trim() : contentType)
        : undefined;
    if (isCurriculumSubject && !effectiveContentType) return;
    const lpPoolValues = availableLearningPerformance.map((e) => e.value);
    const lcPoolValues = availableLearningContent.map((e) => e.value);

    // If no learning_performance selected, pre-draw randomly to match backend sampling
    let finalLp: string[] | undefined;
    let autoDrawn = false;
    if (isCurriculumSubject && learningPerformance.length === 0 && lpPoolValues.length > 0) {
      const maxDraw = subject === "math" ? 3 : 2;
      finalLp = drawRandomSubset(lpPoolValues, 1, maxDraw);
      autoDrawn = true;
    } else if (isCurriculumSubject && learningPerformance.length > 0) {
      finalLp = learningPerformance;
    }

    setLpWasAutoDrawn(autoDrawn);
    let finalLc: string[] | undefined;
    let lcAutoDrawn = false;
    if (
      (subject === "natural_sciences" || subject === "social_studies") &&
      !(subject === "social_studies" && coverageMode === "balanced") &&
      learningContent.length === 0 &&
      lcPoolValues.length > 0
    ) {
      finalLc = drawRandomSubset(lcPoolValues, 1, 3);
      lcAutoDrawn = true;
    } else if (
      (subject === "natural_sciences" || subject === "social_studies") &&
      learningContent.length > 0
    ) {
      finalLc = learningContent;
    }

    setLcWasAutoDrawn(lcAutoDrawn);
    const perSubqLpPool = learningPerformance.length > 0 ? learningPerformance : (finalLp ?? []);
    const perSubqLcPool = learningContent.length > 0 ? learningContent : (finalLc ?? []);
    const shouldDrawPerSubq =
      (subject === "social_studies" || subject === "natural_sciences") &&
      subQuestionCount !== "";

    const effectiveSubquestionConfigsInternal: (SubQuestionConfig & {
      _lcWasAutoDrawn?: boolean;
      _lpWasAutoDrawn?: boolean;
    })[] = shouldDrawPerSubq
      ? subquestionConfigs
          .slice(0, subQuestionCount as number)
          .map((cfg) => {
            const hasExplicitLc = (cfg.learning_content?.length ?? 0) > 0;
            const hasExplicitLp = (cfg.learning_performance?.length ?? 0) > 0;
            const resolvedLc = hasExplicitLc
              ? cfg.learning_content
              : perSubqLcPool.length > 0
                ? drawRandomSubset(perSubqLcPool, 1, 3)
                : undefined;
            const resolvedLp = hasExplicitLp
              ? cfg.learning_performance
              : perSubqLpPool.length > 0
                ? drawRandomSubset(perSubqLpPool, 1, 2)
                : undefined;
            return {
              question_type: cfg.question_type || undefined,
              instruction: cfg.instruction?.trim() || undefined,
              content_type: cfg.content_type || undefined,
              image_generation_mode: cfg.image_generation_mode || undefined,
              question_word_limit: cfg.question_word_limit,
              option_word_limit: cfg.option_word_limit,
              text_word_limit: cfg.text_word_limit,
              reporting_scale: subject === "natural_sciences" ? cfg.reporting_scale || undefined : undefined,
              learning_content: resolvedLc?.length ? resolvedLc : undefined,
              learning_performance: resolvedLp?.length ? resolvedLp : undefined,
              _lcWasAutoDrawn: !hasExplicitLc && !!resolvedLc?.length,
              _lpWasAutoDrawn: !hasExplicitLp && !!resolvedLp?.length,
            };
          })
      : [];

    const effectiveSubquestionConfigs: SubQuestionConfig[] = effectiveSubquestionConfigsInternal.map(
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      ({ _lcWasAutoDrawn: _lc, _lpWasAutoDrawn: _lp, ...rest }) => rest,
    );

    const hasSubquestionConfig = effectiveSubquestionConfigs.some(
      (c) => c.question_type || c.instruction || c.content_type || c.image_generation_mode || c.question_word_limit || c.option_word_limit || c.text_word_limit || c.reporting_scale || c.learning_content?.length || c.learning_performance?.length,
    );
    const shouldSendSubquestionConfigs =
      (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== "" && (
        hasSubquestionConfig || effectiveSubquestionConfigs.length > 0
      );

    setPendingResolvedSubquestionConfigs(effectiveSubquestionConfigsInternal);
    setCoreQuestionResolution(coreQuestion ? "idle" : "loading");
    const baseParams: FormParams = {
      grade,
      style: subject === "math" ? style : undefined,
      content_type: effectiveContentType,
      context: subject === "natural_sciences" ? context.slice(0, 1) : context,
      set_type: setType,
      q_type: subject === "social_studies" ? [] : qType,
      count,
      coverage_mode: subject === "social_studies" ? coverageMode : undefined,
      skip_verify: skipVerify,
      disable_reference_fewshot: disableReferenceFewshot,
      image_generation_mode: imageGenerationMode,
      difficulty: difficulty === "" ? undefined : difficulty,
      subject_filter: subjectFilter || undefined,
      passage: cleanPassage,
      text_word_limit: supportsTextWordLimit ? textWordLimit : undefined,
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
      model_plan: modelPlan || undefined,
      model_execute: modelExecute || undefined,
    };

    let previousQuestionLp: string[] | undefined;
    let previousQuestionLc: string[] | undefined;
    let previousQuestionSubquestions: SubQuestionConfig[] | undefined;
    let previousRandomValues: Record<string, string[] | undefined> = {};
    const drawField = (key: string, pool: string[], max = 1): string[] | undefined => {
      if (userChosenFields.current.has(key) || pool.length === 0) return undefined;
      return drawQuestionSubset(pool, 1, max, previousRandomValues[key]);
    };
    const perQuestionParams = Array.from({ length: count }, (_, questionIndex) => {
      const resolvedSeed = configuredSeed !== undefined
        ? configuredSeed + questionIndex
        : Math.floor(Math.random() * 2_147_483_648);
      const randomStyle = subject === "math"
        ? drawField("style", (schemas?.question_style ?? []).map((entry) => entry.value))
        : undefined;
      const randomContentType = drawField(
        "content_type",
        (schemas?.題目內容類型 ?? []).filter((entry) => entry.value !== "customized").map((entry) => entry.value),
      );
      const randomContext = drawField("context", (schemas?.情境 ?? []).map((entry) => entry.value));
      const randomSetType = drawField("set_type", (schemas?.題型種類 ?? []).map((entry) => entry.value));
      const randomQuestionType = subject !== "social_studies"
        ? drawField("q_type", (schemas?.題型 ?? []).map((entry) => entry.value))
        : undefined;
      const randomSubjectFilter = subject === "social_studies"
        ? drawField("subject_filter", (schemas?.科目 ?? []).map((entry) => entry.value))
        : undefined;
      const randomSubContext = subject === "natural_sciences"
        ? drawField("sub_context", availableSubContexts.map((entry) => entry.value))
        : undefined;
      const randomScienceCompetency = subject === "natural_sciences"
        ? drawField("science_competency", (schemas?.科學能力 ?? []).map((entry) => entry.value))
        : undefined;
      const questionLp = autoDrawn
        ? drawQuestionSubset(lpPoolValues, 1, subject === "math" ? 3 : 2, previousQuestionLp)
        : finalLp;
      const questionLc = lcAutoDrawn
        ? drawQuestionSubset(lcPoolValues, 1, 3, previousQuestionLc)
        : finalLc;
      const questionSubquestionConfigs = shouldDrawPerSubq
        ? subquestionConfigs.slice(0, subQuestionCount as number).map((cfg, subquestionIndex) => {
            const hasExplicitLc = (cfg.learning_content?.length ?? 0) > 0;
            const hasExplicitLp = (cfg.learning_performance?.length ?? 0) > 0;
            const lcPool = learningContent.length > 0 ? learningContent : (questionLc ?? []);
            const lpPool = learningPerformance.length > 0 ? learningPerformance : (questionLp ?? []);
            return {
              question_type: cfg.question_type || undefined,
              instruction: cfg.instruction?.trim() || undefined,
              content_type: cfg.content_type || undefined,
              image_generation_mode: cfg.image_generation_mode || undefined,
              question_word_limit: cfg.question_word_limit,
              option_word_limit: cfg.option_word_limit,
              text_word_limit: cfg.text_word_limit,
              reporting_scale: subject === "natural_sciences" ? cfg.reporting_scale || undefined : undefined,
              learning_content: hasExplicitLc
                ? cfg.learning_content
                : lcPool.length > 0
                  ? drawQuestionSubset(
                      lcPool,
                      1,
                      3,
                      previousQuestionSubquestions?.[subquestionIndex]?.learning_content,
                    )
                  : undefined,
              learning_performance: hasExplicitLp
                ? cfg.learning_performance
                : lpPool.length > 0
                  ? drawQuestionSubset(
                      lpPool,
                      1,
                      2,
                      previousQuestionSubquestions?.[subquestionIndex]?.learning_performance,
                    )
                  : undefined,
            };
          })
        : [];
      const result = {
        ...baseParams,
        seed: resolvedSeed,
        style: randomStyle ?? (baseParams.style ? [baseParams.style] : undefined),
        content_type: randomContentType?.[0] ?? baseParams.content_type,
        context: randomContext ?? baseParams.context,
        set_type: randomSetType?.[0] ?? baseParams.set_type,
        q_type: randomQuestionType ?? baseParams.q_type,
        subject_filter: randomSubjectFilter ?? (baseParams.subject_filter ? [baseParams.subject_filter] : undefined),
        sub_context: randomSubContext?.[0] ?? baseParams.sub_context,
        science_competency: randomScienceCompetency ?? baseParams.science_competency,
        difficulty: baseParams.difficulty ?? "medium",
        model_plan: baseParams.model_plan ?? models?.defaults.plan,
        model_execute: baseParams.model_execute ?? models?.defaults.execute,
        learning_performance: questionLp,
        learning_content: questionLc,
        subquestion_configs: shouldSendSubquestionConfigs
          ? JSON.stringify(questionSubquestionConfigs)
          : undefined,
      };
      previousQuestionLp = questionLp;
      previousQuestionLc = questionLc;
      previousQuestionSubquestions = questionSubquestionConfigs;
      previousRandomValues = {
        style: randomStyle,
        content_type: randomContentType,
        context: randomContext,
        set_type: randomSetType,
        q_type: randomQuestionType,
        subject_filter: randomSubjectFilter,
        sub_context: randomSubContext,
        science_competency: randomScienceCompetency,
      };
      return result;
    });
    setPerQuestionAutoFields(
      perQuestionParams.map(() => [
        ...(configuredSeed === undefined ? ["seed"] : []),
        ...(!userChosenFields.current.has("style") && subject === "math" ? ["style"] : []),
        ...(!userChosenFields.current.has("content_type") ? ["content_type"] : []),
        ...(!userChosenFields.current.has("context") ? ["context"] : []),
        ...(!userChosenFields.current.has("set_type") ? ["set_type"] : []),
        ...(!userChosenFields.current.has("q_type") && subject !== "social_studies" ? ["q_type"] : []),
        ...(!userChosenFields.current.has("subject_filter") && subject === "social_studies" ? ["subject_filter"] : []),
        ...(!userChosenFields.current.has("sub_context") && subject === "natural_sciences" ? ["sub_context"] : []),
        ...(!userChosenFields.current.has("science_competency") && subject === "natural_sciences" ? ["science_competency"] : []),
        ...(autoDrawn ? ["learning_performance"] : []),
        ...(lcAutoDrawn ? ["learning_content"] : []),
      ]),
    );
    setPendingParams({
      ...baseParams,
      per_question_params: JSON.stringify(perQuestionParams),
    });
  }

  function handleConfirmSend() {
    if (!pendingParams) return;
    setPendingParams(null);
    onSubmit(pendingParams);
  }

  if (pendingParams) {
    const p = pendingParams;
    const resolvedPerQuestionParams = p.per_question_params
      ? JSON.parse(p.per_question_params) as Record<string, unknown>[]
      : [];
    const allLpEntries = schemas?.學習表現 ?? [];
    const allLcEntries = schemas?.學習內容 ?? [];

    const allSubjects = ["math", "social_studies", "natural_sciences"];
    const rows = ([
      { label: t("form.confirm_topic"), value: p.topic, subjects: allSubjects, kind: "absent" },
      {
        label: t("form.confirm_core_question"),
        value: p.core_question,
        subjects: allSubjects,
        kind: coreQuestionResolution === "failed" ? "defaulted" : "absent",
        defaultValue: coreQuestionResolution === "failed" ? t("form.confirm_core_question_generation_decides") : undefined,
        badge: coreQuestionResolution === "generated" ? t("form.confirm_core_question_pre_generated") : undefined,
      },
      { label: t("form.confirm_grade"), value: String(p.grade), subjects: allSubjects },
      { label: t("form.confirm_difficulty"), value: p.difficulty, subjects: allSubjects, kind: "defaulted", defaultValue: "medium" },
      { label: t("form.confirm_subject_filter"), value: p.subject_filter, subjects: ["math", "social_studies"], kind: subject === "social_studies" ? "sampled" : "absent" },
      { label: t("form.confirm_count"), value: String(p.count), subjects: allSubjects },
      {
        label: t("form.confirm_coverage_mode"),
        value: subject === "social_studies" ? p.coverage_mode : undefined,
        subjects: ["social_studies"],
      },
      { label: t("form.confirm_passage"), value: p.passage, subjects: allSubjects },
      { label: t("form.confirm_options"), value: p.options?.join(", "), subjects: ["math"] },
      { label: t("form.confirm_text_word_limit"), value: p.text_word_limit !== undefined ? String(p.text_word_limit) : undefined, subjects: ["social_studies", "natural_sciences"], kind: "defaulted", defaultValue: t("form.confirm_unlimited") },
      { label: t("form.confirm_sub_question_count"), value: p.sub_question_count !== undefined ? String(p.sub_question_count) : undefined, subjects: ["social_studies", "natural_sciences"] },
      { label: t("form.confirm_model_plan"), value: p.model_plan, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      { label: t("form.confirm_model_execute"), value: p.model_execute, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      {
        label: t("form.confirm_image_mode"),
        value: p.image_generation_mode,
        subjects: allSubjects,
      },
      { label: t("form.confirm_skip_verify"), value: p.skip_verify ? "✓" : undefined, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_no") },
      {
        label: t("form.confirm_disable_reference_fewshot"),
        value: p.disable_reference_fewshot ? "✓" : undefined,
        subjects: ["social_studies", "natural_sciences"],
        kind: "defaulted",
        defaultValue: t("form.confirm_no"),
      },
    ] satisfies ConfirmationRow[]).filter((row) => row.subjects.includes(subject));
    const perQuestionRows = ([
      { key: "seed", label: t("form.confirm_seed"), subjects: allSubjects },
      { key: "style", label: t("form.confirm_style"), subjects: ["math"] },
      { key: "content_type", label: t("form.confirm_content_type"), subjects: allSubjects },
      { key: "context", label: t("form.confirm_context"), subjects: allSubjects },
      { key: "set_type", label: t("form.confirm_set_type"), subjects: allSubjects },
      { key: "q_type", label: t("form.confirm_q_type"), subjects: ["math", "natural_sciences"] },
      { key: "subject_filter", label: t("form.confirm_subject_filter"), subjects: ["social_studies"] },
      { key: "sub_context", label: t("form.confirm_sub_context"), subjects: ["natural_sciences"] },
      { key: "science_competency", label: t("form.confirm_science_competency"), subjects: ["natural_sciences"] },
    ] satisfies { key: string; label: string; subjects: string[] }[])
      .filter((row) => row.subjects.includes(subject));

    return (
      <div className="space-y-4">
        <div>
          <h2 className="text-base font-semibold">{t("form.confirm_title")}</h2>
          <p className="mt-1 text-sm text-gray-500">{t("form.confirm_subtitle")}</p>
        </div>
        <section role="region" aria-label={t("form.confirm_shared_heading")}>
          <h3 className="mb-3 font-semibold text-gray-800">{t("form.confirm_shared_heading")}</h3>
          <dl className="divide-y rounded-lg border bg-gray-50">
            {rows.map(({ label, value, kind = "absent", defaultValue, badge }) => (
                <div key={label} className="flex gap-3 px-4 py-2.5">
                  <dt className="w-40 shrink-0 text-sm font-medium text-gray-600">{label}</dt>
                  <dd className="flex-1 break-words text-sm text-gray-900">
                    {resolveConfirmationValue(value, kind, t, defaultValue)}
                    {badge && <span className="ml-2 text-xs font-medium text-amber-700">{badge}</span>}
                  </dd>
                </div>
            ))}
          </dl>
        </section>
        <div className="space-y-4">
          {resolvedPerQuestionParams.map((questionParams, index) => {
            const heading = t("form.confirm_question_block").replace("{n}", String(index + 1));
            const questionLpCodes = Array.isArray(questionParams.learning_performance)
              ? questionParams.learning_performance.filter((code): code is string => typeof code === "string")
              : [];
            const questionLcCodes = Array.isArray(questionParams.learning_content)
              ? questionParams.learning_content.filter((code): code is string => typeof code === "string")
              : [];
            const questionLpDisplayEntries = allLpEntries.filter((entry) => questionLpCodes.includes(entry.value));
            const questionLcDisplayEntries = allLcEntries.filter((entry) => questionLcCodes.includes(entry.value));
            const questionSubquestionConfigs = parseSubquestionConfigs(
              questionParams.subquestion_configs,
            ).map((config, subquestionIndex): ResolvedSubQuestionConfig => ({
              ...config,
              _lcWasAutoDrawn: pendingResolvedSubquestionConfigs[subquestionIndex]?._lcWasAutoDrawn,
              _lpWasAutoDrawn: pendingResolvedSubquestionConfigs[subquestionIndex]?._lpWasAutoDrawn,
            }));
            const questionLpHeading = t(
              lpWasAutoDrawn ? "form.confirm_lp_random_pool" : "form.confirm_lp_selected",
            )
              .replace("{n}", String(questionLpDisplayEntries.length));
            const questionLcHeading = t(
              lcWasAutoDrawn ? "form.confirm_lc_random_pool" : "form.confirm_lc_selected",
            )
              .replace("{n}", String(questionLcDisplayEntries.length));
            const textGeneratorPreview = promptPreviews.find(
              (preview) => preview.index === index && preview.subquestion_index === undefined,
            );
            const subquestionGeneratorPreviews = promptPreviews
              .filter(
                (preview) => preview.index === index && preview.subquestion_index !== undefined,
              )
              .sort((a, b) => a.subquestion_index! - b.subquestion_index!);
            return (
              <section
                key={index}
                role="region"
                aria-label={heading}
                className="rounded-lg border border-gray-200 bg-white p-4"
              >
                <h3 className="mb-3 font-semibold text-gray-800">{heading}</h3>
                <dl className="space-y-2">
                  {perQuestionRows.map(({ key, label }) => {
                      const value = questionParams[key];
                      const displayValue = Array.isArray(value)
                        ? value.join(", ")
                        : value === undefined
                          ? undefined
                          : String(value);
                      const isRandom = perQuestionAutoFields[index]?.includes(key);
                      const isPredrawnSeed = key === "seed" && isRandom;
                      return (
                        <div key={key} className="flex gap-3 text-sm">
                          <dt className="w-40 shrink-0 font-medium text-gray-600">
                            {label}
                          </dt>
                          <dd className="min-w-0 break-words text-gray-900">
                            <span>{resolveConfirmationValue(displayValue, "absent", t)}</span>
                            <span className={`ml-2 text-xs font-medium ${isRandom ? "text-amber-700" : "text-green-700"}`}>
                              {isPredrawnSeed
                                ? t("form.confirm_seed_predrawn")
                                : t(isRandom ? "form.confirm_badge_random" : "form.confirm_badge_user")}
                            </span>
                          </dd>
                        </div>
                      );
                    })}
                  <div className="flex gap-3 text-sm">
                      <dt className="w-40 shrink-0 font-medium text-gray-600">{t("form.confirm_learning_performance")}</dt>
                      <dd className="min-w-0 flex-1 text-gray-900">
                        {questionLpDisplayEntries.length === 0 ? (
                          <span className="italic text-gray-400">{t("form.confirm_not_filled")}</span>
                        ) : (
                          <div className="space-y-1">
                            <p className={`mb-1.5 text-xs font-medium ${lpWasAutoDrawn ? "text-amber-700" : "text-green-700"}`}>{questionLpHeading}</p>
                            <ul className="space-y-1">
                              {questionLpDisplayEntries.map((entry) => (
                                <li key={entry.value} className="flex gap-2 text-sm">
                                  <span className="shrink-0 font-mono font-semibold text-gray-800">{entry.value}</span>
                                  {entry.instruction && <span className="text-gray-600">— {entry.instruction}</span>}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </dd>
                  </div>
                  <div className="flex gap-3 text-sm">
                      <dt className="w-40 shrink-0 font-medium text-gray-600">{t("form.confirm_learning_content")}</dt>
                      <dd className="min-w-0 flex-1 text-gray-900">
                        {questionLcDisplayEntries.length === 0 ? (
                          <span className="italic text-gray-400">
                            {subject === "social_studies" && p.coverage_mode === "balanced"
                              ? t("form.confirm_lc_balanced_backend_assignment")
                              : t("form.confirm_not_filled")}
                          </span>
                        ) : (
                          <div className="space-y-1">
                            <p className={`mb-1.5 text-xs font-medium ${lcWasAutoDrawn ? "text-amber-700" : "text-green-700"}`}>{questionLcHeading}</p>
                            <ul className="space-y-1">
                              {questionLcDisplayEntries.map((entry) => (
                                <li key={entry.value} className="flex gap-2 text-sm">
                                  <span className="shrink-0 font-mono font-semibold text-gray-800">{entry.value}</span>
                                  {entry.instruction && <span className="text-gray-600">— {entry.instruction}</span>}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </dd>
                  </div>
                </dl>
                {questionSubquestionConfigs.length > 0 && (
                  <section className="mt-4 space-y-3 border-t pt-4">
                    <h4 className="text-sm font-semibold text-gray-700">{t("form.confirm_subquestion_heading")}</h4>
                    <ol className="space-y-3">
                      {questionSubquestionConfigs.map((row, subquestionIndex) => (
                        <li key={subquestionIndex} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                          <h5 className="mb-2 text-xs font-semibold text-gray-600">
                            {t("form.confirm_subquestion_row_title").replace("{n}", String(subquestionIndex + 1))}
                          </h5>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_q_type")} {row.question_type ?? t("form.confirm_random")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_instruction")} {row.instruction ?? t("form.confirm_not_filled")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_content_type")} {row.content_type ?? t("form.confirm_inherit_text")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_image_mode")} {row.image_generation_mode ?? t("form.confirm_inherit_text")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_q_word_limit")} {row.question_word_limit ?? t("form.confirm_unlimited")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_o_word_limit")} {row.option_word_limit ?? t("form.confirm_unlimited")}</div>
                          <div className="text-sm text-gray-700">{t("form.confirm_subq_text_word_limit")} {row.text_word_limit ?? t("form.confirm_unlimited")}</div>
                          {subject === "natural_sciences" && <div className="text-sm text-gray-700">{t("form.confirm_subq_reporting_scale")} {row.reporting_scale ?? t("form.confirm_random")}</div>}
                          <div>
                            {row.learning_content && row.learning_content.length > 0 ? (
                              <>
                                <div className="mt-2 text-xs font-medium text-gray-600">
                                  {t(
                                    row._lcWasAutoDrawn
                                      ? "form.confirm_subq_lc_random_pool"
                                      : "form.confirm_subq_lc_selected",
                                  ).replace("{n}", String(row.learning_content.length))}
                                </div>
                                <ul className="list-disc pl-5 text-sm text-gray-700">
                                  {row.learning_content.map((code) => <li key={code}>{code}</li>)}
                                </ul>
                              </>
                            ) : (
                              <div className="text-sm text-gray-700">{t("form.confirm_subq_lc_empty")}</div>
                            )}
                          </div>
                          <div>
                            {row.learning_performance && row.learning_performance.length > 0 ? (
                              <>
                                <div className="mt-2 text-xs font-medium text-gray-600">
                                  {t(
                                    row._lpWasAutoDrawn
                                      ? "form.confirm_subq_lp_random_pool"
                                      : "form.confirm_subq_lp_selected",
                                  ).replace("{n}", String(row.learning_performance.length))}
                                </div>
                                <ul className="list-disc pl-5 text-sm text-gray-700">
                                  {row.learning_performance.map((code) => <li key={code}>{code}</li>)}
                                </ul>
                              </>
                            ) : (
                              <div className="text-sm text-gray-700">{t("form.confirm_subq_lp_empty")}</div>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}
                {textGeneratorPreview && (
                  <details className="mt-4 border-t border-gray-200 pt-3">
                    <summary className="cursor-pointer text-sm font-semibold text-gray-700">
                      {t("form.confirm_text_generator_prompt_preview")}
                    </summary>
                    <div className="mt-3 space-y-3">
                      <div>
                        <div className="mb-1 text-xs font-medium text-gray-600">
                          {t("form.confirm_system_prompt")}
                        </div>
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs text-gray-800">
                          {textGeneratorPreview.system_prompt}
                        </pre>
                      </div>
                      <div>
                        <div className="mb-1 text-xs font-medium text-gray-600">
                          {t("form.confirm_user_prompt")}
                        </div>
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs text-gray-800">
                          {textGeneratorPreview.user_prompt}
                        </pre>
                      </div>
                    </div>
                  </details>
                )}
                {subquestionGeneratorPreviews.map((preview) => (
                  <details
                    key={preview.subquestion_index}
                    className="mt-4 border-t border-gray-200 pt-3"
                  >
                    <summary className="cursor-pointer text-sm font-semibold text-gray-700">
                      {t("form.confirm_subquestion_generator_prompt_preview")
                        .replace("{n}", String(preview.subquestion_index! + 1))}
                    </summary>
                    <div className="mt-3 space-y-3">
                      <div>
                        <div className="mb-1 text-xs font-medium text-gray-600">
                          {t("form.confirm_system_prompt")}
                        </div>
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs text-gray-800">
                          {preview.system_prompt}
                        </pre>
                      </div>
                      <div>
                        <div className="mb-1 text-xs font-medium text-gray-600">
                          {t("form.confirm_user_prompt")}
                        </div>
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs text-gray-800">
                          {preview.user_prompt}
                        </pre>
                      </div>
                    </div>
                  </details>
                ))}
              </section>
            );
          })}
        </div>
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
      {prefillNotice && (
        <div className="mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800">
          {prefillNotice}
        </div>
      )}
      {validationError && (
        <div role="alert" className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          {validationError}
        </div>
      )}
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
        <label htmlFor="param-form-grade" className="block text-sm font-medium">{t("form.grade")}</label>
        <select
          id="param-form-grade"
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
        <label htmlFor="difficulty" className="block text-sm font-medium">
          {t("form.difficulty")}
        </label>
        <select
          id="difficulty"
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value as "" | "easy" | "medium" | "hard")}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          <option value="">{t("form.difficulty_default")}</option>
          <option value="easy">{t("form.difficulty_easy")}</option>
          <option value="medium">{t("form.difficulty_medium")}</option>
          <option value="hard">{t("form.difficulty_hard")}</option>
        </select>
      </div>

      {schemas.科目 && schemas.科目.length > 0 && (
        <div>
          <label className="block text-sm font-medium">
            {t(
              subject === "natural_sciences"
                ? "form.subject_filter_natural_sciences"
                : "form.subject_filter",
            )}
          </label>
          <select
            value={subjectFilter}
            onChange={(e) => {
              markUserChosen("subject_filter");
              setSubjectFilter(e.target.value);
            }}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="">{t("form.subject_filter.all")}</option>
            {schemas.科目.map((s) => (
              <option key={s.value} value={s.value}>
                {s.value}
              </option>
            ))}
          </select>
          {subject === "natural_sciences" && (
            <p className="mt-1 text-sm text-gray-500">
              {t("form.subject_filter_natural_sciences_help")}
            </p>
          )}
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
                  onChange={(values) => {
                    markUserChosen("learning_performance");
                    setLearningPerformance(values);
                  }}
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
                      onChange={() => {
                        markUserChosen("learning_performance");
                        setLearningPerformance((prev) => toggleMulti(prev, entry.value));
                      }}
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
            onChange={(e) => {
              markUserChosen("style");
              setStyle(e.target.value);
            }}
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
            onChange={(e) => {
              markUserChosen("content_type");
              setContentType(e.target.value);
            }}
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
                  onChange={() => {
                    markUserChosen("context");
                    setContext((prev) => toggleMulti(prev, s.value));
                  }}
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
              onChange={(e) => {
                markUserChosen("context");
                setContext(e.target.value ? [e.target.value] : []);
              }}
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
              onChange={(e) => {
                markUserChosen("sub_context");
                setSubContext(e.target.value);
              }}
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
          onChange={(e) => {
            markUserChosen("set_type");
            setSetType(e.target.value);
            setValidationError(null);
          }}
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
                onChange={() => {
                  markUserChosen("q_type");
                  setQType((prev) => toggleMulti(prev, s.value));
                }}
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
                  onChange={() => {
                    markUserChosen("science_competency");
                    setScienceCompetency((prev) => toggleMulti(prev, s.value));
                  }}
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
                  onChange={(values) => {
                    markUserChosen("learning_content");
                    setLearningContent(values);
                  }}
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
                      onChange={() => {
                        markUserChosen("learning_content");
                        setLearningContent((prev) => toggleMulti(prev, entry.value));
                      }}
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

      {subject === "social_studies" && (
        <div>
          <label htmlFor="coverage-mode-select" className="block text-sm font-medium">
            {t("form.coverage_mode")}
          </label>
          <select
            id="coverage-mode-select"
            aria-label="form.coverage_mode"
            value={coverageMode}
            onChange={(e) => setCoverageMode(e.target.value as "balanced" | "random")}
            className="mt-1 block w-64 border rounded px-2 py-1"
          >
            <option value="balanced">{t("form.coverage_mode.balanced")}</option>
            <option value="random">{t("form.coverage_mode.random")}</option>
          </select>
        </div>
      )}

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
                    {subject === "natural_sciences" && (
                      <div>
                        <label className="block text-xs text-gray-500">報告等級</label>
                        <select
                          value={cfg.reporting_scale || ""}
                          onChange={(e) => updateSubquestionConfig(i, { reporting_scale: e.target.value || undefined })}
                          className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
                        >
                          <option value="">（隨機）</option>
                          <option value="1c">等級 1c</option>
                          <option value="1b">等級 1b</option>
                          <option value="1a">等級 1a</option>
                          <option value="2">等級 2</option>
                          <option value="3">等級 3</option>
                          <option value="4">等級 4</option>
                          <option value="5">等級 5</option>
                          <option value="6">等級 6</option>
                        </select>
                      </div>
                    )}
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

      {supportsTextWordLimit && (
        <div>
          <label className="block text-sm font-medium">{t("form.text_word_limit")}</label>
          <input
            type="number"
            min={1}
            value={textWordLimit ?? ""}
            onChange={(e) => setTextWordLimit(e.target.value ? Number(e.target.value) : undefined)}
            placeholder={t("form.unlimited")}
            className="mt-1 block w-full border rounded px-2 py-1"
          />
        </div>
      )}

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

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={disableReferenceFewshot}
            onChange={(e) => setDisableReferenceFewshot(e.target.checked)}
          />
          <span className="text-sm">{t("form.disable_reference_fewshot")}</span>
        </label>
      )}

      {isCurriculumSubject && topic.trim() && !coreQuestion && (
        <p role="status" className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          ⚠ {t("form.topic_no_pick_warning")}
        </p>
      )}

      {models && models.allowed.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-gray-700">
            <span>{t("params.model_plan_label")}</span>
            <select
              aria-label={t("params.model_plan_label")}
              value={modelPlan}
              onChange={(e) => setModelPlan(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">
                {t("params.model_default_option")} ({models.defaults.plan})
              </option>
              {models.allowed.map((m) => (
                <option key={`plan-${m}`} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-700">
            <span>{t("params.model_execute_label")}</span>
            <select
              aria-label={t("params.model_execute_label")}
              value={modelExecute}
              onChange={(e) => setModelExecute(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">
                {t("params.model_default_option")} ({models.defaults.execute})
              </option>
              {models.allowed.map((m) => (
                <option key={`exec-${m}`} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
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
