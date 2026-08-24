import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getAvailableModels, getSchemas, planCoreQuestions, previewGenerate, type AvailableModels, type PromptPreview, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import { clearDraft, loadDraft, saveDraft, type FormDraft } from "../lib/formDraft";
import { renewSessionIfNeeded } from "../lib/sessionRenewal";
import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import { drawRandomSubset } from "../utils/drawRandomSubset";
import {
  findSocialStudiesPinRuleViolations,
  type SocialStudiesPinRuleViolation,
} from "../utils/socialStudiesPinRules";
import CoreQuestionPicker from "./CoreQuestionPicker";
import SubQuestionConfigEditor from "./SubQuestionConfigEditor";
import SubQuestionCurriculumPickers, { SearchPicker } from "./SubQuestionCurriculumPickers";
import SubquestionConfigCards, { type ResolvedSubQuestionConfig } from "./SubquestionConfigCards";
import type { GenerateParams as WireGenerateParams } from "../api/generated/contract";
import { toGenerateParams } from "../utils/toGenerateParams";

export interface SubQuestionConfig {
  question_type?: string;
  cognitive_process?: string;
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

function parsePerQuestionParams(value: unknown): Record<string, unknown>[] {
  const parsed = (() => {
    if (Array.isArray(value)) return value;
    if (typeof value !== "string") return null;
    try {
      return JSON.parse(value) as unknown;
    } catch {
      return null;
    }
  })();
  if (
    !Array.isArray(parsed) ||
    parsed.some(
      (row) => typeof row !== "object" || row === null || Array.isArray(row),
    )
  ) {
    return [];
  }
  return parsed as Record<string, unknown>[];
}

function parsePredrawnFields(value: unknown): Set<string> | null {
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed) || parsed.some((field) => typeof field !== "string")) {
      return null;
    }
    return new Set(parsed);
  } catch {
    return null;
  }
}

function serialisableSubquestionConfig(config: SubQuestionConfig): SubQuestionConfig {
  return Object.fromEntries(
    Object.entries(config).filter(([, value]) => value !== undefined),
  ) as SubQuestionConfig;
}

const RETIRED_SOCIAL_PREFILL_KEYS = ["閱讀歷程", "文本形式", "question_style"] as const;
const RETIRED_SOCIAL_QUESTION_TYPE = "封閉式建構反應題";

type HistoryPrefillNoticeCollector = {
  items: string[];
  seen: Set<string>;
};

type NormalisedHistoryPrefill = {
  params: Record<string, unknown>;
  retiredItems: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function historyPrefillValueText(value: unknown): string {
  if (Array.isArray(value)) {
    const values = value.map(historyPrefillValueText).filter(Boolean);
    return values.length > 0 ? values.join("、") : "（空）";
  }
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function addHistoryPrefillNotice(
  collector: HistoryPrefillNoticeCollector,
  field: string,
  value: unknown,
  location?: string,
): void {
  const valueText = historyPrefillValueText(value);
  // Repeated copies of the same retired field/value do not add useful noise;
  // question-type pins retain their location so each cleared slot is named.
  const dedupeKey = field === "題型"
    ? `${field}|${valueText}|${location ?? ""}`
    : `${field}|${valueText}`;
  if (collector.seen.has(dedupeKey)) return;
  collector.seen.add(dedupeKey);
  const locationText = location ? `，${location}` : "";
  collector.items.push(`${field}（${valueText}${locationText}）`);
}

function parseHistoryArray(value: unknown): unknown[] | null {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function normaliseRetiredQuestionType(
  value: unknown,
  collector: HistoryPrefillNoticeCollector,
  location?: string,
): unknown {
  if (Array.isArray(value)) {
    return value.filter((entry) => {
      if (entry !== RETIRED_SOCIAL_QUESTION_TYPE) return true;
      addHistoryPrefillNotice(collector, "題型", entry, location);
      return false;
    });
  }
  if (value === RETIRED_SOCIAL_QUESTION_TYPE) {
    addHistoryPrefillNotice(collector, "題型", value, location);
    return undefined;
  }
  return value;
}

function normaliseHistorySubquestionConfigs(
  value: unknown,
  collector: HistoryPrefillNoticeCollector,
  questionIndex?: number,
): unknown {
  const rows = parseHistoryArray(value);
  if (!rows) return value;
  const normalisedRows = rows.map((row, subquestionIndex) => {
    if (!isRecord(row)) return row;
    const location = questionIndex === undefined
      ? `第${subquestionIndex + 1}小題`
      : `第${questionIndex + 1}題第${subquestionIndex + 1}小題`;
    return normaliseHistoryRecord(row, collector, location, questionIndex);
  });
  return typeof value === "string" ? JSON.stringify(normalisedRows) : normalisedRows;
}

function normaliseHistoryRecord(
  record: Record<string, unknown>,
  collector: HistoryPrefillNoticeCollector,
  subquestionLocation?: string,
  questionIndex?: number,
): Record<string, unknown> {
  const normalised: Record<string, unknown> = { ...record };

  for (const key of RETIRED_SOCIAL_PREFILL_KEYS) {
    if (!Object.hasOwn(record, key)) continue;
    addHistoryPrefillNotice(collector, key, record[key]);
    delete normalised[key];
  }

  if (Object.hasOwn(normalised, "q_type")) {
    const questionType = normaliseRetiredQuestionType(
      normalised.q_type,
      collector,
      questionIndex === undefined ? undefined : `第${questionIndex + 1}題`,
    );
    if (questionType === undefined) delete normalised.q_type;
    else normalised.q_type = questionType;
  }

  if (Object.hasOwn(normalised, "question_type")) {
    const questionType = normalised.question_type;
    if (questionType === RETIRED_SOCIAL_QUESTION_TYPE) {
      addHistoryPrefillNotice(collector, "題型", questionType, subquestionLocation);
      delete normalised.question_type;
    }
  }

  if (Object.hasOwn(normalised, "subquestion_configs")) {
    normalised.subquestion_configs = normaliseHistorySubquestionConfigs(
      normalised.subquestion_configs,
      collector,
      questionIndex,
    );
  }

  if (Object.hasOwn(normalised, "per_question_params")) {
    const rows = parseHistoryArray(normalised.per_question_params);
    if (rows) {
      const normalisedRows = rows.map((row, index) =>
        isRecord(row)
          ? normaliseHistoryRecord(row, collector, undefined, index)
          : row,
      );
      normalised.per_question_params = typeof normalised.per_question_params === "string"
        ? JSON.stringify(normalisedRows)
        : normalisedRows;
    }
  }

  return normalised;
}

function normaliseHistoryPrefill(
  subject: string,
  initialParams: Record<string, unknown> | undefined,
): NormalisedHistoryPrefill {
  const params = initialParams ? { ...initialParams } : {};
  if (subject !== "social_studies") return { params, retiredItems: [] };

  const collector: HistoryPrefillNoticeCollector = { items: [], seen: new Set() };
  return {
    params: normaliseHistoryRecord(params, collector),
    retiredItems: collector.items,
  };
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
  onUnsubmittedInput?: () => void;
}

/**
 * Complete, JSON-serialisable snapshot of the user-entered generation fields.
 * Async data, validation/confirmation state, and display-only UI preferences
 * deliberately live outside this object.
 */
export interface FormFields {
  grade: number | "";
  style: string;
  contentType: string;
  customContentType: string;
  context: string[];
  setType: string;
  qType: string[];
  count: number;
  coverageMode: "balanced" | "random";
  skipVerify: boolean;
  disableReferenceFewshot: boolean;
  coreQuestionCallback: boolean;
  imageGenerationMode: "html" | "gpt_image";
  difficulty: "" | "easy" | "medium" | "hard";
  reportingScale: string;
  subjectFilter: string;
  passage: string;
  textWordLimit: number | null;
  options: string[];
  topic: string;
  coreQuestion: string | null;
  subContext: string;
  scienceCompetency: string[];
  learningPerformance: string[];
  learningContent: string[];
  subQuestionCount: number | "";
  subquestionConfigs: SubQuestionConfig[];
  modelPlan: string;
  modelExecute: string;
  modelVerify: string;
  modelCorrect: string;
  effortPlan: string;
  effortExecute: string;
  effortVerify: string;
  effortCorrect: string;
  // Optional for backwards compatibility with drafts saved before #493.
  contentDomain?: string;
  targetSurface?: "紙本" | "數位";
}

type FormFieldUpdate<K extends keyof FormFields> =
  | FormFields[K]
  | ((current: FormFields[K]) => FormFields[K]);

function jsonDeepEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => jsonDeepEqual(value, right[index]))
    );
  }
  if (
    typeof left !== "object" ||
    left === null ||
    typeof right !== "object" ||
    right === null
  ) {
    return false;
  }

  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord);
  const rightKeys = Object.keys(rightRecord);
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every(
      (key) =>
        Object.hasOwn(rightRecord, key) &&
        jsonDeepEqual(leftRecord[key], rightRecord[key]),
    )
  );
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

function formatDraftRelativeTime(savedAt: string, locale: string): string {
  const differenceMs = Date.parse(savedAt) - Date.now();
  const absoluteDifferenceMs = Math.abs(differenceMs);
  const dayMs = 24 * 60 * 60 * 1_000;
  const hourMs = 60 * 60 * 1_000;
  const minuteMs = 60 * 1_000;
  const [divisor, unit] =
    absoluteDifferenceMs >= dayMs
      ? [dayMs, "day" as const]
      : absoluteDifferenceMs >= hourMs
        ? [hourMs, "hour" as const]
        : [minuteMs, "minute" as const];

  return new Intl.RelativeTimeFormat(locale, { numeric: "always" }).format(
    Math.round(differenceMs / divisor),
    unit,
  );
}

function truncateDraftPassage(passage: string): string {
  const characters = Array.from(passage);
  return characters.length > 80
    ? `${characters.slice(0, 80).join("")}…`
    : passage;
}

type DraftSummarySettingRow = {
  label: string;
  value?: string;
  content?: ReactNode;
};

function DraftSummary({
  fields,
  lang,
  t,
  subject,
  schemas,
}: {
  fields: FormFields;
  lang: string;
  t: (key: string) => string;
  subject: string;
  schemas: Schemas | null;
}) {
  const lcEntryByCode = new Map(
    (schemas?.學習內容 ?? []).map((entry) => [entry.value, entry]),
  );
  const lpEntryByCode = new Map(
    (schemas?.學習表現 ?? []).map((entry) => [entry.value, entry]),
  );

  return (
    <>
      <section
        role="region"
        aria-label={t("form.draft_summary")}
        className="mt-3"
      >
        <dl className="space-y-1 rounded border border-amber-200 bg-white/60 p-2">
          {[
            { label: t("form.confirm_topic"), value: fields.topic },
            {
              label: t("form.confirm_core_question"),
              value: fields.coreQuestion ?? "",
            },
            { label: t("form.grade"), value: String(fields.grade) },
            {
              label: t("form.subject_filter"),
              value: fields.subjectFilter,
            },
            { label: t("form.count"), value: String(fields.count) },
            ...(fields.subQuestionCount === ""
              ? []
              : [{
                  label: t("form.confirm_sub_question_count"),
                  value: String(fields.subQuestionCount),
                }]),
            {
              label: t("form.q_type"),
              value: fields.qType.join(lang === "zh-TW" ? "、" : ", "),
            },
            {
              label: t("form.context"),
              value: fields.context.join(lang === "zh-TW" ? "、" : ", "),
            },
            ...(fields.passage
              ? [{
                  label: t("form.confirm_passage"),
                  value: truncateDraftPassage(fields.passage),
                  isPassage: true,
                }]
              : []),
          ].map(({ label, value, isPassage }) => {
            const displayValue = value || t("form.confirm_not_filled");
            return (
              <div key={label} className="flex min-w-0 gap-3">
                <dt className="w-24 shrink-0 font-medium text-amber-800">{label}</dt>
                <dd
                  className={`min-w-0 flex-1 text-amber-950 ${
                    isPassage ? "max-h-16 overflow-hidden break-words" : ""
                  }`}
                >
                  {displayValue}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>
      <details className="mt-3 border-t border-amber-200 pt-2">
        <summary className="cursor-pointer font-medium text-amber-800">
          {t("form.draft_full_settings")}
        </summary>
        <dl className="mt-2 space-y-1 rounded border border-amber-200 bg-white/60 p-2">
          {[
            { label: t("form.style"), value: fields.style },
            {
              label: t("form.content_type"),
              value:
                fields.contentType === "customized"
                  ? t("form.content_type_customized")
                  : fields.contentType,
            },
            {
              label: t("form.custom_content_type"),
              value: fields.customContentType,
            },
            { label: t("form.set_type"), value: fields.setType },
            {
              label: t("form.coverage_mode"),
              value: t(`form.coverage_mode.${fields.coverageMode}`),
            },
            {
              label: t("form.skip_verify"),
              value: t(
                fields.skipVerify
                  ? "form.confirm_yes"
                  : "form.confirm_no",
              ),
            },
            {
              label: t("form.disable_reference_fewshot"),
              value: t(
                fields.disableReferenceFewshot
                  ? "form.confirm_yes"
                  : "form.confirm_no",
              ),
            },
            {
              label: t("form.image_generation_mode"),
              value: t(
                fields.imageGenerationMode === "gpt_image"
                  ? "form.image_generation_mode_gpt"
                  : "form.image_generation_mode_html",
              ),
            },
            {
              label: t("form.difficulty"),
              value: fields.difficulty
                ? t(`form.difficulty_${fields.difficulty}`)
                : "",
            },
            {
              label: t("form.confirm_reporting_scale"),
              value: fields.reportingScale,
            },
            {
              label: t("form.text_word_limit"),
              value:
                fields.textWordLimit === null
                  ? t("form.confirm_unlimited")
                  : String(fields.textWordLimit),
            },
            {
              label: t("form.confirm_options"),
              value: fields.options.join(lang === "zh-TW" ? "、" : ", "),
            },
            {
              label: t("form.sub_context"),
              value: fields.subContext,
            },
            {
              label: t("form.science_competency"),
              value: fields.scienceCompetency.join(
                lang === "zh-TW" ? "、" : ", ",
              ),
            },
            {
              label: t("form.learning_performance"),
              ...(fields.learningPerformance.length > 0
                ? {
                    content: (
                      <ul className="space-y-1">
                        {fields.learningPerformance.map((code) => {
                          const entry = lpEntryByCode.get(code);
                          return (
                            <li key={code} className="flex gap-2 text-sm">
                              <span className="shrink-0 font-mono font-semibold text-gray-800">
                                {code}
                              </span>
                              {entry?.instruction && (
                                <span className="text-gray-600">
                                  — {entry.instruction}
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    ),
                  }
                : { value: "" }),
            },
            {
              label: t("form.learning_content"),
              ...(fields.learningContent.length > 0
                ? {
                    content: (
                      <ul className="space-y-1">
                        {fields.learningContent.map((code) => {
                          const entry = lcEntryByCode.get(code);
                          return (
                            <li key={code} className="flex gap-2 text-sm">
                              <span className="shrink-0 font-mono font-semibold text-gray-800">
                                {code}
                              </span>
                              {entry?.instruction && (
                                <span className="text-gray-600">
                                  — {entry.instruction}
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    ),
                  }
                : { value: "" }),
            },
            {
              label: t("form.confirm_subquestion_heading"),
              ...(fields.subquestionConfigs.length > 0
                ? {
                    content: (
                      <SubquestionConfigCards
                        configs={fields.subquestionConfigs}
                        subject={subject}
                        lcEntryByCode={lcEntryByCode}
                        lpEntryByCode={lpEntryByCode}
                      />
                    ),
                  }
                : { value: "" }),
            },
            {
              label: t("params.model_plan_label"),
              value: fields.modelPlan,
            },
            {
              label: t("params.model_execute_label"),
              value: fields.modelExecute,
            },
            {
              label: t("params.model_verify_label"),
              value: fields.modelVerify,
            },
            {
              label: t("params.model_correct_label"),
              value: fields.modelCorrect,
            },
            {
              label: t("form.effort_verify"),
              value: fields.effortVerify,
            },
            {
              label: t("form.effort_correct"),
              value: fields.effortCorrect,
            },
          ].map(({ label, value, content }: DraftSummarySettingRow) => {
            const displayValue =
              content !== undefined
                ? content
                : value !== undefined && value !== ""
                  ? value
                  : t("form.confirm_not_filled");
            return (
              <div key={label} className="flex min-w-0 gap-3">
                <dt className="w-40 shrink-0 font-medium text-amber-800">{label}</dt>
                <dd className="min-w-0 flex-1 break-words text-amber-950">
                  {displayValue}
                </dd>
              </div>
            );
          })}
        </dl>
      </details>
    </>
  );
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
const DEFAULT_CONTENT_TYPE = "含圖片";

function defaultFormFields(
  subject: string,
  schemas: Schemas,
  modelPlan: string,
  modelExecute: string,
  modelVerify: string,
  modelCorrect: string,
  effortPlan: string,
  effortExecute: string,
  effortVerify: string,
  effortCorrect: string,
): FormFields {
  const isCurriculumSubject =
    subject === "social_studies" ||
    subject === "math" ||
    subject === "natural_sciences";
  const firstContext = schemas.情境[0]?.value;
  const defaultNaturalSciencesContext =
    subject === "natural_sciences" && firstContext ? [firstContext] : [];
  const defaultSubContext =
    subject === "natural_sciences" && firstContext
      ? (schemas.情境子類別 ?? []).find(
          (entry) => entry.parent === firstContext,
        )?.value ?? ""
      : "";
  const contentTypes =
    schemas.題目內容類型 as Schemas["題目內容類型"] | undefined;

  return {
    grade: schemas.grades[0] ?? "",
    style:
      subject === "math"
        ? (schemas.question_style?.[0]?.value ?? "")
        : "",
    contentType:
      isCurriculumSubject &&
      Array.isArray(contentTypes) &&
      contentTypes.length > 0
        ? (contentTypes.find((t) => t.value === DEFAULT_CONTENT_TYPE)?.value ??
            contentTypes[0].value)
        : "純文字",
    customContentType: "",
    context: defaultNaturalSciencesContext,
    setType: schemas.題型種類[0]?.value ?? "",
    qType: [],
    count: 1,
    coverageMode: "balanced",
    skipVerify: false,
    disableReferenceFewshot: false,
    coreQuestionCallback: true,
    imageGenerationMode: "gpt_image",
    difficulty: "",
    reportingScale: "",
    subjectFilter: "",
    passage: TEXT_HINT,
    textWordLimit: null,
    options: [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT],
    topic: "",
    coreQuestion: null,
    subContext: defaultSubContext,
    scienceCompetency: [],
    learningPerformance: [],
    learningContent: [],
    subQuestionCount: "",
    subquestionConfigs: [],
    modelPlan,
    modelExecute,
    modelVerify,
    modelCorrect,
    effortPlan,
    effortExecute,
    effortVerify,
    effortCorrect,
    contentDomain: "",
    targetSurface: "紙本",
  };
}

const SUBJECT_TO_PERFORMANCE_PREFIXES: Record<string, string[]> = {
  "": ["社"],
  "歷史": ["歷", "社"],
  "地理": ["地", "社"],
  "公民與社會": ["公", "社"],
  "跨科": ["歷", "地", "公", "社"],
};
const MATH_SUBJECT_TO_STRAND_PREFIXES: Record<string, string[]> = {
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

const PIN_RULE_MESSAGE_KEYS: Record<SocialStudiesPinRuleViolation, string> = {
  knowing_defining_limit: "form.pin_rule.knowing_defining_limit",
  cross_subject_relate: "form.pin_rule.cross_subject_relate",
};

export default function ParamForm({
  subject = "math",
  onSubmit,
  disabled,
  initialParams,
  onUnsubmittedInput,
}: ParamFormProps) {
  const generationStartedRef = useRef(false);
  const hasUserEditedRef = useRef(false);
  const markUnsubmittedInput = () => {
    generationStartedRef.current = false;
    hasUserEditedRef.current = true;
    onUnsubmittedInput?.();
  };
  const t = useT();
  const lang = useLangStore((state) => state.lang);
  const [schemas, setSchemas] = useState<Schemas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);
  const [surfaceQuestionTypeNotice, setSurfaceQuestionTypeNotice] = useState<string[]>([]);
  const [pendingParams, setPendingParams] = useState<FormParams | null>(null);
  const [pendingPerQuestionParams, setPendingPerQuestionParams] = useState<Record<string, unknown>[] | null>(null);
  const [coreQuestionResolution, setCoreQuestionResolution] = useState<"idle" | "loading" | "generated" | "failed">("idle");
  const [lpWasAutoDrawn, setLpWasAutoDrawn] = useState(false);
  const [lcWasAutoDrawn, setLcWasAutoDrawn] = useState(false);
  const [pendingResolvedSubquestionConfigs, setPendingResolvedSubquestionConfigs] = useState<
    ResolvedSubQuestionConfig[][]
  >([]);
  const [perQuestionAutoFields, setPerQuestionAutoFields] = useState<string[][]>([]);
  const [promptPreviews, setPromptPreviews] = useState<PromptPreview[]>([]);
  const [models, setModels] = useState<AvailableModels | null>(null);
  const [modelsResolved, setModelsResolved] = useState(false);
  const [useCurriculumSearch, setUseCurriculumSearch] = useState<boolean>(true);
  const previewRequestedRef = useRef(false);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const hasInitialParams =
    initialParams !== undefined && Object.keys(initialParams).length > 0;
  const [draftToRestore, setDraftToRestore] = useState<FormDraft | null>(() =>
    userId ? loadDraft(userId) : null,
  );
  const [historyDraftChoice, setHistoryDraftChoice] = useState<
    "draft" | "history" | "defaults" | null
  >(null);

  const normalisedHistoryPrefill = useMemo(
    () => normaliseHistoryPrefill(subject, initialParams),
    [initialParams, subject],
  );
  const ip = normalisedHistoryPrefill.params;
  const historyPredrawnFields = parsePredrawnFields(ip.predrawn_fields);
  const userChosenFields = useRef(
    new Set(Object.keys(ip).filter((key) => !historyPredrawnFields?.has(key))),
  );
  function fromInit<T>(key: string, fallback: T): T {
    return (ip[key] as T | undefined) ?? fallback;
  }
  function stringFromInit(key: string, fallback: string): string {
    const value = ip[key];
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    return fallback;
  }
  function subquestionConfigsFromInit(): SubQuestionConfig[] {
    const value = ip.subquestion_configs;
    const configs = Array.isArray(value)
      ? value.filter(
          (row): row is SubQuestionConfig =>
            typeof row === "object" && row !== null && !Array.isArray(row),
        )
      : parseSubquestionConfigs(value);
    return configs.map(serialisableSubquestionConfig);
  }
  function markUserChosen(key: string) {
    userChosenFields.current.add(key);
  }

  const [formFields, setFormFields] = useState<FormFields>(() => ({
    grade: fromInit<number | "">("grade", ""),
    style: stringFromInit("style", ""),
    contentType: fromInit<string>("content_type", DEFAULT_CONTENT_TYPE),
    customContentType: "",
    context: fromInit<string[]>("context", []),
    setType: fromInit<string>("set_type", ""),
    qType: fromInit<string[]>("q_type", []),
    count: fromInit<number>("count", 1),
    coverageMode: ip.coverage_mode === "random" ? "random" : "balanced",
    skipVerify: fromInit<boolean>("skip_verify", false),
    disableReferenceFewshot: fromInit<boolean>("disable_reference_fewshot", false),
    coreQuestionCallback: fromInit<boolean>("core_question_callback", true),
    imageGenerationMode: fromInit<"html" | "gpt_image">("image_generation_mode", "gpt_image"),
    difficulty: fromInit<"" | "easy" | "medium" | "hard">("difficulty", ""),
    reportingScale: fromInit<string>("reporting_scale", ""),
    subjectFilter: (() => {
      const value = fromInit<string | string[]>("subject_filter", "");
      return Array.isArray(value) ? (value[0] ?? "") : value;
    })(),
    passage: stringFromInit("passage", TEXT_HINT),
    textWordLimit: fromInit<number | undefined>("text_word_limit", undefined) ?? null,
    options: fromInit<string[]>(
      "options",
      [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT],
    ),
    topic: fromInit<string>("topic", ""),
    coreQuestion: fromInit<string | null>("core_question", null),
    subContext: fromInit<string>("sub_context", ""),
    scienceCompetency: fromInit<string[]>("science_competency", []),
    learningPerformance: historyPredrawnFields?.has("learning_performance")
      ? []
      : fromInit<string[]>("learning_performance", []),
    learningContent: historyPredrawnFields?.has("learning_content")
      ? []
      : fromInit<string[]>("learning_content", []),
    subQuestionCount: fromInit<number | "">("sub_question_count", ""),
    subquestionConfigs: subquestionConfigsFromInit(),
    contentDomain: stringFromInit("content_domain", ""),
    targetSurface: ip.target_surface === "數位" ? "數位" : "紙本",
    modelPlan: stringFromInit("model_plan", window.localStorage.getItem("model_plan") ?? ""),
    modelExecute: stringFromInit("model_execute", window.localStorage.getItem("model_execute") ?? ""),
    modelVerify: stringFromInit("model_verify", window.localStorage.getItem("model_verify") ?? ""),
    modelCorrect: stringFromInit("model_correct", window.localStorage.getItem("model_correct") ?? ""),
    effortPlan: stringFromInit("effort_plan", window.localStorage.getItem("effort_plan") ?? "medium"),
    effortExecute: stringFromInit("effort_execute", window.localStorage.getItem("effort_execute") ?? "medium"),
    effortVerify: stringFromInit("effort_verify", window.localStorage.getItem("effort_verify") ?? ""),
    effortCorrect: stringFromInit("effort_correct", window.localStorage.getItem("effort_correct") ?? ""),
  }));
  const formSnapshot = formFields;
  const restoreFormSnapshot = setFormFields;
  const defaultsSnapshotRef = useRef<FormFields | null>(null);
  const draftSaveTimeoutRef = useRef<number | null>(null);
  const [defaultsReady, setDefaultsReady] = useState(false);
  const setField = useCallback(
    function updateFormField<K extends keyof FormFields>(key: K, update: FormFieldUpdate<K>) {
      restoreFormSnapshot((current) => {
        const nextValue = typeof update === "function"
          ? (update as (value: FormFields[K]) => FormFields[K])(current[key])
          : update;
        if (Object.is(nextValue, current[key])) return current;
        return { ...current, [key]: nextValue };
      });
    },
    [restoreFormSnapshot],
  );
  const {
    grade,
    style,
    contentType,
    customContentType,
    context,
    setType,
    qType,
    count,
    coverageMode,
    skipVerify,
    disableReferenceFewshot,
    coreQuestionCallback,
    imageGenerationMode,
    difficulty,
    reportingScale,
    subjectFilter,
    passage,
    textWordLimit,
    options,
    topic,
    coreQuestion,
    subContext,
    scienceCompetency,
    learningPerformance,
    learningContent,
    subQuestionCount,
    subquestionConfigs,
    modelPlan,
    modelExecute,
    modelVerify,
    modelCorrect,
    effortPlan,
    effortExecute,
    effortVerify,
    effortCorrect,
    contentDomain,
    targetSurface,
  } = formSnapshot;
  const configuredSeed = fromInit<number | undefined>("seed", undefined);
  const historyPerQuestionParams = parsePerQuestionParams(ip.per_question_params);
  const pinRuleViolations = useMemo(
    () => subject === "social_studies"
      ? findSocialStudiesPinRuleViolations(subquestionConfigs, subjectFilter)
      : [],
    [subject, subjectFilter, subquestionConfigs],
  );

  useEffect(() => {
    let cancelled = false;
    void renewSessionIfNeeded(() => cancelled).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!schemas) return;
    if (defaultsSnapshotRef.current === null) {
      defaultsSnapshotRef.current = formSnapshot;
    }
    if (modelsResolved && !defaultsReady) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- defaultsReady gates the draft restore UI after async model discovery
      setDefaultsReady(true);
    }
  }, [defaultsReady, formSnapshot, modelsResolved, schemas]);

  const hasDraftHistoryConflict =
    draftToRestore !== null &&
    hasInitialParams &&
    historyDraftChoice === null;

  useEffect(() => {
    if (
      !userId ||
      !defaultsReady ||
      generationStartedRef.current ||
      hasDraftHistoryConflict ||
      (
        (historyDraftChoice === "history" ||
          historyDraftChoice === "defaults") &&
        !hasUserEditedRef.current
      ) ||
      (hasInitialParams && !hasUserEditedRef.current) ||
      defaultsSnapshotRef.current === null ||
      (
        !hasInitialParams &&
        jsonDeepEqual(formSnapshot, defaultsSnapshotRef.current)
      )
    ) {
      return;
    }

    const timeout = window.setTimeout(() => {
      draftSaveTimeoutRef.current = null;
      saveDraft(userId, formSnapshot);
    }, 1_000);
    draftSaveTimeoutRef.current = timeout;
    return () => {
      window.clearTimeout(timeout);
      if (draftSaveTimeoutRef.current === timeout) {
        draftSaveTimeoutRef.current = null;
      }
    };
  }, [
    defaultsReady,
    formSnapshot,
    hasDraftHistoryConflict,
    hasInitialParams,
    historyDraftChoice,
    userId,
  ]);

  /* eslint-disable react-hooks/refs -- draft restore prompts intentionally compare non-render state captured by refs */
  const showDraftPrompt =
    draftToRestore !== null &&
    defaultsReady &&
    !hasInitialParams &&
    !hasUserEditedRef.current &&
    defaultsSnapshotRef.current !== null &&
    jsonDeepEqual(formSnapshot, defaultsSnapshotRef.current);
  /* eslint-enable react-hooks/refs */
  const showDraftHistoryChoice =
    hasDraftHistoryConflict &&
    defaultsReady;

  function handleRestoreDraft() {
    if (!draftToRestore) return;
    const fields = draftToRestore.fields;
    if (hasInitialParams) {
      setHistoryDraftChoice("draft");
      setPrefillNotice(null);
    }
    setDraftToRestore(null);
    restoreFormSnapshot({
      ...fields,
      contentDomain: fields.contentDomain ?? "",
      targetSurface: fields.targetSurface ?? "紙本",
    });
  }

  function handleUseHistoryParams() {
    hasUserEditedRef.current = false;
    setHistoryDraftChoice("history");
    setDraftToRestore(null);
    if (defaultsSnapshotRef.current !== null) {
      restoreFormSnapshot(defaultsSnapshotRef.current);
    }
  }

  function handleStartWithDefaults() {
    if (!schemas) return;
    hasUserEditedRef.current = false;
    setHistoryDraftChoice("defaults");
    setDraftToRestore(null);
    setPrefillNotice(null);
    userChosenFields.current.clear();
    restoreFormSnapshot(
      defaultFormFields(subject, schemas, modelPlan, modelExecute, modelVerify, modelCorrect, effortPlan, effortExecute, effortVerify, effortCorrect),
    );
  }

  function handleRestartDraft() {
    if (userId) clearDraft(userId);
    setDraftToRestore(null);
  }

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
      setPendingPerQuestionParams((current) =>
        current?.map((item) => ({ ...item, core_question: selected })) ?? current,
      );
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
  const isCurriculumSubject =
    subject === "social_studies" || subject === "math" || subject === "natural_sciences";
  const supportsTextWordLimit = isCurriculumSubject;
  const hasUserAuthoredMathPassage =
    subject === "math" && passage !== TEXT_HINT && passage.trim().length > 0;
  const canUseTextWordLimit = supportsTextWordLimit && !hasUserAuthoredMathPassage;

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- schema reload resets the form while switching subject
    setSchemas(null);
    setError(null);
    restoreFormSnapshot((current) => ({
      ...current,
      context: fromInit<string[]>("context", []),
      qType: fromInit<string[]>("q_type", []),
      imageGenerationMode: fromInit<"html" | "gpt_image">(
        "image_generation_mode",
        "gpt_image",
      ),
      difficulty: fromInit<"" | "easy" | "medium" | "hard">("difficulty", ""),
      passage: fromInit<string>("passage", TEXT_HINT),
      textWordLimit: fromInit<number | undefined>("text_word_limit", undefined) ?? null,
      options: fromInit<string[]>(
        "options",
        [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT],
      ),
      subjectFilter: (() => {
        const v = fromInit<string | string[]>("subject_filter", "");
        return Array.isArray(v) ? (v[0] ?? "") : v;
      })(),
      subContext: fromInit<string>("sub_context", ""),
      scienceCompetency: fromInit<string[]>("science_competency", []),
      learningPerformance: historyPredrawnFields?.has("learning_performance")
        ? []
        : fromInit<string[]>("learning_performance", []),
      learningContent: historyPredrawnFields?.has("learning_content")
        ? []
        : fromInit<string[]>("learning_content", []),
      subQuestionCount: fromInit<number | "">("sub_question_count", ""),
      subquestionConfigs: subquestionConfigsFromInit(),
      contentDomain: stringFromInit("content_domain", ""),
      targetSurface: ip.target_surface === "數位" ? "數位" : "紙本",
      topic: fromInit<string>("topic", ""),
      coreQuestion: fromInit<string | null>("core_question", null),
      coreQuestionCallback: fromInit<boolean>("core_question_callback", true),
    }));
    getSchemas(subject)
      .then((s) => {
        if (cancelled) return;
        setSchemas(s);
        if (s.grades.length > 0 && ip.grade === undefined) setField("grade", s.grades[0]);
        if (
          subject === "natural_sciences" &&
          s.情境.length > 0 &&
          ip.sub_context === undefined
        ) {
          setField("context", [s.情境[0].value]);
          const firstSub = (s.情境子類別 ?? []).find(
            (entry) => entry.parent === s.情境[0].value,
          );
          setField("subContext", firstSub?.value ?? "");
        }
        const questionStyles = s.question_style ?? [];
        if (ip.style === undefined) {
          if (subject === "math" && questionStyles.length > 0) {
            setField("style", questionStyles[0].value);
          } else {
            setField("style", "");
          }
        }
        if (ip.content_type === undefined) {
          const contentTypes = s.題目內容類型 as Schemas["題目內容類型"] | undefined;
          setField(
            "contentType",
            isCurriculumSubject &&
              Array.isArray(contentTypes) &&
              contentTypes.length > 0
              ? (contentTypes.find((t) => t.value === DEFAULT_CONTENT_TYPE)?.value ??
                  contentTypes[0].value)
              : "純文字",
          );
          markUserChosen("content_type");
        }
        setField("customContentType", "");
        if (s.題型種類.length > 0 && ip.set_type === undefined) setField("setType", s.題型種類[0].value);
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
        // Effort levels are also reconciled atomically: if the persisted
        // effort is not supported by the reconciled model, fall back to
        // defaults.effort_plan / defaults.effort_execute ("medium").
        const allowed = new Set(m.allowed);
        const reconcileEffortLevel = (
          effortValue: string,
          modelId: string,
          effortMap: Record<string, string[]> | undefined,
          defaultEffort: string,
        ): string => {
          if (!effortMap || !modelId || !effortMap[modelId]) return effortValue;
          const levels = effortMap[modelId];
          return levels.includes(effortValue) ? effortValue : defaultEffort;
        };
        const defaultEffortPlan = m.defaults.effort_plan ?? "medium";
        const defaultEffortExecute = m.defaults.effort_execute ?? "medium";
        // For tier effort levels, the effective model is the tier model (if set),
        // falling back to the execute model or server default.
        const reconcileTierEffortLevel = (
          effortValue: string,
          tierModelId: string,
          executeModelId: string,
          defaultExecuteModelId: string,
          effortMap: Record<string, string[]> | undefined,
        ): string => {
          if (effortValue === "") return ""; // "" = inherit, always valid
          if (!effortMap) return effortValue;
          const effectiveModel = tierModelId || executeModelId || defaultExecuteModelId;
          if (!effectiveModel || !effortMap[effectiveModel]) return effortValue;
          const levels = effortMap[effectiveModel];
          return levels.includes(effortValue) ? effortValue : "";
        };

        restoreFormSnapshot((current) => {
          const reconciledPlan =
            current.modelPlan && !allowed.has(current.modelPlan)
              ? ""
              : current.modelPlan;
          const reconciledExecute =
            current.modelExecute && !allowed.has(current.modelExecute)
              ? ""
              : current.modelExecute;
          const reconciledVerify =
            current.modelVerify && !allowed.has(current.modelVerify)
              ? ""
              : current.modelVerify;
          const reconciledCorrect =
            current.modelCorrect && !allowed.has(current.modelCorrect)
              ? ""
              : current.modelCorrect;
          return {
            ...current,
            modelPlan: reconciledPlan,
            modelExecute: reconciledExecute,
            modelVerify: reconciledVerify,
            modelCorrect: reconciledCorrect,
            effortPlan: reconcileEffortLevel(
              current.effortPlan,
              reconciledPlan,
              m.effort,
              defaultEffortPlan,
            ),
            effortExecute: reconcileEffortLevel(
              current.effortExecute,
              reconciledExecute,
              m.effort,
              defaultEffortExecute,
            ),
            effortVerify: reconcileTierEffortLevel(
              current.effortVerify,
              reconciledVerify,
              reconciledExecute,
              m.defaults.execute,
              m.effort,
            ),
            effortCorrect: reconcileTierEffortLevel(
              current.effortCorrect,
              reconciledCorrect,
              reconciledExecute,
              m.defaults.execute,
              m.effort,
            ),
          };
        });

        if (defaultsSnapshotRef.current) {
          const snap = defaultsSnapshotRef.current;
          const reconciledPlanSnap =
            snap.modelPlan && !allowed.has(snap.modelPlan)
              ? ""
              : snap.modelPlan;
          const reconciledExecuteSnap =
            snap.modelExecute && !allowed.has(snap.modelExecute)
              ? ""
              : snap.modelExecute;
          const reconciledVerifySnap =
            snap.modelVerify && !allowed.has(snap.modelVerify)
              ? ""
              : snap.modelVerify;
          const reconciledCorrectSnap =
            snap.modelCorrect && !allowed.has(snap.modelCorrect)
              ? ""
              : snap.modelCorrect;
          defaultsSnapshotRef.current = {
            ...snap,
            modelPlan: reconciledPlanSnap,
            modelExecute: reconciledExecuteSnap,
            modelVerify: reconciledVerifySnap,
            modelCorrect: reconciledCorrectSnap,
            effortPlan: reconcileEffortLevel(
              snap.effortPlan,
              reconciledPlanSnap,
              m.effort,
              defaultEffortPlan,
            ),
            effortExecute: reconcileEffortLevel(
              snap.effortExecute,
              reconciledExecuteSnap,
              m.effort,
              defaultEffortExecute,
            ),
            effortVerify: reconcileTierEffortLevel(
              snap.effortVerify,
              reconciledVerifySnap,
              reconciledExecuteSnap,
              m.defaults.execute,
              m.effort,
            ),
            effortCorrect: reconcileTierEffortLevel(
              snap.effortCorrect,
              reconciledCorrectSnap,
              reconciledExecuteSnap,
              m.defaults.execute,
              m.effort,
            ),
          };
        }
        setModelsResolved(true);
      })
      .catch(() => {
        if (cancelled) return;
        // Discovery failure: hide the dropdowns AND clear any selection —
        // the binding is that no model_plan/model_execute is ever sent
        // when /api/models fails, even for a returning user with a
        // persisted choice.
        setModels(null);
        if (defaultsSnapshotRef.current) {
          defaultsSnapshotRef.current = {
            ...defaultsSnapshotRef.current,
            modelPlan: "",
            modelExecute: "",
            modelVerify: "",
            modelCorrect: "",
            effortPlan: "",
            effortExecute: "",
            effortVerify: "",
            effortCorrect: "",
          };
        }
        setField("modelPlan", "");
        setField("modelExecute", "");
        setField("modelVerify", "");
        setField("modelCorrect", "");
        setField("effortPlan", "");
        setField("effortExecute", "");
        setField("effortVerify", "");
        setField("effortCorrect", "");
        setModelsResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, [restoreFormSnapshot, setField]);

  useEffect(() => {
    window.localStorage.setItem("model_plan", modelPlan);
  }, [modelPlan]);
  useEffect(() => {
    window.localStorage.setItem("model_execute", modelExecute);
  }, [modelExecute]);
  useEffect(() => {
    window.localStorage.setItem("model_verify", modelVerify);
  }, [modelVerify]);
  useEffect(() => {
    window.localStorage.setItem("model_correct", modelCorrect);
  }, [modelCorrect]);
  useEffect(() => {
    window.localStorage.setItem("effort_plan", effortPlan);
  }, [effortPlan]);
  useEffect(() => {
    window.localStorage.setItem("effort_execute", effortExecute);
  }, [effortExecute]);
  useEffect(() => {
    window.localStorage.setItem("effort_verify", effortVerify);
  }, [effortVerify]);
  useEffect(() => {
    window.localStorage.setItem("effort_correct", effortCorrect);
  }, [effortCorrect]);

  useEffect(() => {
    if (!schemas || !initialParams) return;
    const missing: string[] = [];
    const arr = (key: string): string[] => {
      const raw = ip[key];
      return Array.isArray(raw)
        ? raw.filter((value): value is string => typeof value === "string")
        : [];
    };
    const single = (key: string): string | undefined => {
      const raw = ip[key];
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
    const domain = single("content_domain");
    if (domain !== undefined) {
      check("內容領域", [domain], schemas.內容領域?.map((s) => s.value));
    }
    if (missing.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reconciling initialParams against freshly-loaded schemas, matches existing HistoryPage/VerifyPage pattern
      setPrefillNotice([
        normalisedHistoryPrefill.retiredItems.length > 0
          ? t("form.history_prefill_retired_notice").replace(
              "{items}",
              normalisedHistoryPrefill.retiredItems.join("、"),
            )
          : null,
        t("history.prefill_notice"),
      ].filter((message): message is string => message !== null).join(" "));
      // Drop the missing entries so the form submits a clean payload.
      const allowedCtx = new Set(schemas.情境?.map((s) => s.value));
      setField("context", (prev) => prev.filter((v) => allowedCtx.has(v)));
      const allowedQT = new Set(schemas.題型?.map((s) => s.value));
      setField("qType", (prev) => prev.filter((v) => allowedQT.has(v)));
      const allowedST = new Set(schemas.題型種類?.map((s) => s.value));
      setField("setType", (prev) => (allowedST.has(prev) ? prev : ""));
      const allowedDomains = new Set(schemas.內容領域?.map((s) => s.value));
      setField("contentDomain", (prev) => (prev && allowedDomains.has(prev) ? prev : ""));
    } else {
      setPrefillNotice(
        normalisedHistoryPrefill.retiredItems.length > 0
          ? t("form.history_prefill_retired_notice").replace(
              "{items}",
              normalisedHistoryPrefill.retiredItems.join("、"),
            )
          : null,
      );
    }
  }, [schemas, initialParams, ip, normalisedHistoryPrefill, t, setField]);

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
      subject === "math" ? MATH_SUBJECT_TO_STRAND_PREFIXES : SUBJECT_TO_PERFORMANCE_PREFIXES;
    const prefixes = map[subjectFilter] ?? map[""];
    return entries.filter((entry) => prefixes.includes(entry.科目));
  }, [schemas, subjectFilter, subject]);

  const availableSubContexts = useMemo(() => {
    const entries = schemas?.情境子類別 ?? [];
    const selectedContext = context[0] ?? "";
    return entries.filter((entry) => !entry.parent || entry.parent === selectedContext);
  }, [schemas, context]);

  const availableQuestionTypes = useMemo(() => {
    const entries = schemas?.題型 ?? [];
    if (subject !== "social_studies" || (targetSurface ?? "紙本") !== "紙本") {
      return entries;
    }
    const digitalOnly = new Set(schemas?.digital_only_question_types ?? []);
    return entries.filter((entry) => !digitalOnly.has(entry.value));
  }, [schemas, subject, targetSurface]);

  const invalidDigitalOnlyPins = useMemo(() => {
    if (subject !== "social_studies" || (targetSurface ?? "紙本") !== "紙本") return [];
    const digitalOnly = new Set(schemas?.digital_only_question_types ?? []);
    return [...new Set(
      subquestionConfigs
        .map((config) => config.question_type)
        .filter((value): value is string => value !== undefined && digitalOnly.has(value)),
    )];
  }, [schemas, subject, subquestionConfigs, targetSurface]);

  useEffect(() => {
    if (invalidDigitalOnlyPins.length === 0) return;
    // A schema update or a surface flip can expose a stale history pin. Clear
    // it before submit so the backend never receives a known 422 combination.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setField("subquestionConfigs", (prev) => prev.map((config) =>
      config.question_type !== undefined && invalidDigitalOnlyPins.includes(config.question_type)
        ? { ...config, question_type: undefined }
        : config,
    ));
    setSurfaceQuestionTypeNotice(invalidDigitalOnlyPins);
  }, [invalidDigitalOnlyPins, setField]);

  const availableLearningContent = useMemo(() => {
    const entries = schemas?.學習內容 ?? [];
    if (subject === "math") {
      const prefixes =
        MATH_SUBJECT_TO_STRAND_PREFIXES[subjectFilter] ?? MATH_SUBJECT_TO_STRAND_PREFIXES[""];
      return entries.filter((entry) => prefixes.includes(entry.科目));
    }
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

  const planEffortLevels = useMemo((): string[] => {
    if (!models?.effort) return [];
    if (modelPlan && models.effort[modelPlan]) return models.effort[modelPlan];
    return [...new Set(Object.values(models.effort).flat())];
  }, [models, modelPlan]);

  const executeEffortLevels = useMemo((): string[] => {
    if (!models?.effort) return [];
    if (modelExecute && models.effort[modelExecute]) return models.effort[modelExecute];
    return [...new Set(Object.values(models.effort).flat())];
  }, [models, modelExecute]);

  // For verify/correct tiers, effective model = tier model || execute model || server default.
  const verifyEffortLevels = useMemo((): string[] => {
    if (!models?.effort) return [];
    const effectiveModel = modelVerify || modelExecute || models.defaults.execute;
    if (effectiveModel && models.effort[effectiveModel]) return models.effort[effectiveModel];
    return [...new Set(Object.values(models.effort).flat())];
  }, [models, modelVerify, modelExecute]);

  const correctEffortLevels = useMemo((): string[] => {
    if (!models?.effort) return [];
    const effectiveModel = modelCorrect || modelExecute || models.defaults.execute;
    if (effectiveModel && models.effort[effectiveModel]) return models.effort[effectiveModel];
    return [...new Set(Object.values(models.effort).flat())];
  }, [models, modelCorrect, modelExecute]);

  useEffect(() => {
    if (subject !== "natural_sciences" || !schemas || availableSubContexts.length === 0) return;
    const allowed = new Set(availableSubContexts.map((entry) => entry.value));
    if (!subContext || !allowed.has(subContext)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- fill the first valid dependent sub-context after schema load
      setField("subContext", availableSubContexts[0]?.value ?? "");
    }
  }, [availableSubContexts, schemas, subContext, subject, setField]);

  useEffect(() => {
    if (!schemas) return;
    const allowed = new Set(availableLearningPerformance.map((entry) => entry.value));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reconcile history/draft curriculum selections with the loaded pool
    setField("learningPerformance", (prev) => prev.filter((value) => allowed.has(value)));
    setField("subquestionConfigs", (prev) =>
      prev.map((cfg) =>
        cfg.learning_performance?.length
          ? { ...cfg, learning_performance: cfg.learning_performance.filter((v) => allowed.has(v)) }
          : cfg,
      ),
    );
  }, [availableLearningPerformance, schemas, setField]);

  useEffect(() => {
    if (!schemas) return;
    const allowed = new Set(availableLearningContent.map((entry) => entry.value));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reconcile history/draft curriculum selections with the loaded pool
    setField("learningContent", (prev) => prev.filter((value) => allowed.has(value)));
  }, [availableLearningContent, schemas, setField]);

  // Sync per-subquestion config rows with the selected count.
  useEffect(() => {
    const n = typeof subQuestionCount === "number" ? subQuestionCount : 0;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- keep the editor row count synchronized with the selected count
    setField("subquestionConfigs", (prev) => {
      if (n <= 0) return [];
      if (prev.length === n) return prev;
      if (prev.length < n) return [...prev, ...Array(n - prev.length).fill({})];
      return prev.slice(0, n);
    });
  }, [subQuestionCount, setField]);

  function updateSubquestionConfig(index: number, patch: Partial<SubQuestionConfig>) {
    setField("subquestionConfigs", (prev) => prev.map((cfg, i) =>
      i === index ? serialisableSubquestionConfig({ ...cfg, ...patch }) : cfg,
    ));
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
    const hasHistoryPerQuestionParams = historyPerQuestionParams.length === count;
    const preserveHistoryPerQuestionParams =
      hasHistoryPerQuestionParams && historyPredrawnFields === null;

    // If no learning_performance selected, pre-draw randomly to match backend sampling
    let finalLp: string[] | undefined;
    let autoDrawn = false;
    if (!preserveHistoryPerQuestionParams && isCurriculumSubject && learningPerformance.length === 0 && lpPoolValues.length > 0) {
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
      !preserveHistoryPerQuestionParams &&
      (subject === "math" || subject === "natural_sciences" || subject === "social_studies") &&
      learningContent.length === 0 &&
      lcPoolValues.length > 0
    ) {
      finalLc = drawRandomSubset(lcPoolValues, 1, 3);
      lcAutoDrawn = true;
    } else if (
      (subject === "math" || subject === "natural_sciences" || subject === "social_studies") &&
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
    const builtSubquestionAutoFields: ResolvedSubQuestionConfig[][] = [];

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
              cognitive_process: subject === "social_studies" ? cfg.cognitive_process || undefined : undefined,
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
      (c) => c.question_type || c.cognitive_process || c.instruction || c.content_type || c.image_generation_mode || c.question_word_limit || c.option_word_limit || c.text_word_limit || c.reporting_scale || c.learning_content?.length || c.learning_performance?.length,
    );
    const shouldSendSubquestionConfigs =
      (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== "" && (
        hasSubquestionConfig || effectiveSubquestionConfigs.length > 0
      );

    const hasHistoryCoreQuestion = hasHistoryPerQuestionParams &&
      historyPerQuestionParams.some(
        (params) => typeof params.core_question === "string" && params.core_question.length > 0,
      );
    setCoreQuestionResolution(coreQuestion || hasHistoryCoreQuestion ? "idle" : "loading");
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
      difficulty: subject !== "natural_sciences" ? (difficulty === "" ? undefined : difficulty) : undefined,
      reporting_scale: subject === "natural_sciences" ? (reportingScale === "" ? undefined : reportingScale) : undefined,
      ...(subject === "social_studies" || subject === "natural_sciences"
        ? { core_question_callback: coreQuestionCallback }
        : {}),
      subject_filter: subjectFilter || undefined,
      passage: cleanPassage,
      text_word_limit: canUseTextWordLimit ? (textWordLimit ?? undefined) : undefined,
      options: subject === "math" && cleanOptions.length ? cleanOptions : undefined,
      topic:
        isCurriculumSubject && cleanTopic
          ? cleanTopic
          : undefined,
      core_question: coreQuestion || undefined,
      ...(subject === "social_studies" && contentDomain
        ? { content_domain: contentDomain }
        : {}),
      ...(subject === "social_studies" && targetSurface === "數位"
        ? { target_surface: "數位" as const }
        : {}),
      learning_performance: finalLp,
      sub_context: subject === "natural_sciences" ? subContext : undefined,
      science_competency:
        subject === "natural_sciences" && scienceCompetency.length > 0
          ? scienceCompetency
          : undefined,
      learning_content:
        finalLc,
      sub_question_count: (subject === "social_studies" || subject === "math" || subject === "natural_sciences") && subQuestionCount !== "" ? subQuestionCount : undefined,
      subquestion_configs:
        shouldSendSubquestionConfigs
          ? JSON.stringify(effectiveSubquestionConfigs)
          : undefined,
      model_plan: modelPlan || undefined,
      model_execute: modelExecute || undefined,
      model_verify: modelVerify || undefined,
      model_correct: modelCorrect || undefined,
      effort_plan: models?.effort ? effortPlan : undefined,
      effort_execute: models?.effort ? effortExecute : undefined,
      effort_verify: models?.effort ? (effortVerify || undefined) : undefined,
      effort_correct: models?.effort ? (effortCorrect || undefined) : undefined,
    };
    const requestLevelFields = new Set([
      "subject",
      "count",
      "per_question_params",
      "predrawn_fields",
      "max_retries",
      "core_question_callback",
    ]);
    const perQuestionBase = Object.fromEntries(
      Object.entries(baseParams).filter(
        ([key]) =>
          !requestLevelFields.has(key) &&
          !(subject === "math" && key === "text_word_limit"),
      ),
    );

    let previousQuestionLp: string[] | undefined;
    let previousQuestionLc: string[] | undefined;
    let previousQuestionSubquestions: SubQuestionConfig[] | undefined;
    let previousRandomValues: Record<string, string[] | undefined> = {};
    const builtPerQuestionAutoFields: string[][] = [];
    const predrawnFields: string[] = [
      ...(autoDrawn ? ["learning_performance"] : []),
      ...(lcAutoDrawn ? ["learning_content"] : []),
    ];
    const drawField = (key: string, pool: string[], questionIndex: number, max = 1): string[] | undefined => {
      const fieldAddress = `per_question_params[${questionIndex}].${key}`;
      if (historyPredrawnFields?.has(fieldAddress)) {
        return pool.length > 0
          ? drawQuestionSubset(pool, 1, max, previousRandomValues[key])
          : undefined;
      }
      if (hasHistoryPerQuestionParams && historyPredrawnFields !== null) return undefined;
      if (userChosenFields.current.has(key) || pool.length === 0) return undefined;
      return drawQuestionSubset(pool, 1, max, previousRandomValues[key]);
    };
    const buildPerQuestionParams = () => Array.from({ length: count }, (_, questionIndex) => {
      const historyQuestionParams = hasHistoryPerQuestionParams
        ? historyPerQuestionParams[questionIndex]
        : undefined;
      const seedAddress = `per_question_params[${questionIndex}].seed`;
      const seedWasPredrawn = historyPredrawnFields?.has(seedAddress) ?? false;
      const resolvedSeed = historyQuestionParams?.seed !== undefined && !seedWasPredrawn
        ? historyQuestionParams.seed
        : configuredSeed !== undefined
          ? configuredSeed + questionIndex
          : Math.floor(Math.random() * 2_147_483_648);
      const randomStyle = subject === "math"
        ? drawField("style", (schemas?.question_style ?? []).map((entry) => entry.value), questionIndex)
        : undefined;
      const randomContentType = drawField(
        "content_type",
        (schemas?.題目內容類型 ?? []).filter((entry) => entry.value !== "customized").map((entry) => entry.value),
        questionIndex,
      );
      const randomContext = drawField("context", (schemas?.情境 ?? []).map((entry) => entry.value), questionIndex);
      const randomSetType = drawField("set_type", (schemas?.題型種類 ?? []).map((entry) => entry.value), questionIndex);
      const randomQuestionType = subject !== "social_studies"
        ? drawField("q_type", (schemas?.題型 ?? []).map((entry) => entry.value), questionIndex)
        : undefined;
      const randomSubjectFilter = subject === "social_studies"
        ? drawField("subject_filter", (schemas?.科目 ?? []).map((entry) => entry.value), questionIndex)
        : undefined;
      const randomSubContext = subject === "natural_sciences"
        ? drawField("sub_context", availableSubContexts.map((entry) => entry.value), questionIndex)
        : undefined;
      const randomScienceCompetency = subject === "natural_sciences"
        ? drawField("science_competency", (schemas?.科學能力 ?? []).map((entry) => entry.value), questionIndex)
        : undefined;
      const questionLpAddress = `per_question_params[${questionIndex}].learning_performance`;
      const questionLcAddress = `per_question_params[${questionIndex}].learning_content`;
      const redrawQuestionLp = historyPredrawnFields?.has(questionLpAddress) ||
        (!historyQuestionParams && autoDrawn);
      const redrawQuestionLc = historyPredrawnFields?.has(questionLcAddress) ||
        (!historyQuestionParams && lcAutoDrawn);
      const questionLpPool = learningPerformance.length > 0
        ? learningPerformance
        : autoDrawn
          ? lpPoolValues
          : (finalLp ?? lpPoolValues);
      const questionLcPool = learningContent.length > 0
        ? learningContent
        : lcAutoDrawn
          ? lcPoolValues
          : (finalLc ?? lcPoolValues);
      const historyQuestionLp = Array.isArray(historyQuestionParams?.learning_performance)
        ? historyQuestionParams.learning_performance.filter((code): code is string => typeof code === "string")
        : undefined;
      const historyQuestionLc = Array.isArray(historyQuestionParams?.learning_content)
        ? historyQuestionParams.learning_content.filter((code): code is string => typeof code === "string")
        : undefined;
      const questionLp = redrawQuestionLp
        ? drawQuestionSubset(questionLpPool, 1, subject === "math" ? 3 : 2, previousQuestionLp)
        : (historyQuestionLp ?? finalLp);
      const questionLc = redrawQuestionLc
        ? drawQuestionSubset(questionLcPool, 1, 3, previousQuestionLc)
        : (historyQuestionLc ?? finalLc);
      const questionPredrawnFields: string[] = [
        ...(seedWasPredrawn || (!historyQuestionParams && configuredSeed === undefined)
          ? [seedAddress]
          : []),
        ...(randomStyle !== undefined
          ? [`per_question_params[${questionIndex}].style`]
          : []),
        ...(randomContentType !== undefined
          ? [`per_question_params[${questionIndex}].content_type`]
          : []),
        ...(randomContext !== undefined
          ? [`per_question_params[${questionIndex}].context`]
          : []),
        ...(randomSetType !== undefined
          ? [`per_question_params[${questionIndex}].set_type`]
          : []),
        ...(randomQuestionType !== undefined
          ? [`per_question_params[${questionIndex}].q_type`]
          : []),
        ...(randomSubjectFilter !== undefined
          ? [`per_question_params[${questionIndex}].subject_filter`]
          : []),
        ...(randomSubContext !== undefined
          ? [`per_question_params[${questionIndex}].sub_context`]
          : []),
        ...(randomScienceCompetency !== undefined
          ? [`per_question_params[${questionIndex}].science_competency`]
          : []),
        ...(redrawQuestionLp && questionLp?.length
          ? [questionLpAddress]
          : []),
        ...(redrawQuestionLc && questionLc?.length
          ? [questionLcAddress]
          : []),
      ];
      let hasRedrawnSubquestion = false;
      const questionSubquestionAutoFields: ResolvedSubQuestionConfig[] = [];
      const sourceSubquestionConfigs = historyQuestionParams
        ? parseSubquestionConfigs(historyQuestionParams.subquestion_configs)
        : subquestionConfigs;
      const questionSubquestionConfigs = shouldDrawPerSubq
        ? sourceSubquestionConfigs.slice(0, subQuestionCount as number).map((cfg, subquestionIndex) => {
            const hasExplicitLc = (cfg.learning_content?.length ?? 0) > 0;
            const hasExplicitLp = (cfg.learning_performance?.length ?? 0) > 0;
            const lcPool = learningContent.length > 0 ? learningContent : (questionLc ?? perSubqLcPool);
            const lpPool = learningPerformance.length > 0 ? learningPerformance : (questionLp ?? perSubqLpPool);
            const lcAddress = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].learning_content`;
            const lpAddress = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].learning_performance`;
            const redrawLc = historyPredrawnFields?.has(lcAddress) || (!historyQuestionParams && !hasExplicitLc);
            const redrawLp = historyPredrawnFields?.has(lpAddress) || (!historyQuestionParams && !hasExplicitLp);
            const resolvedLc = redrawLc
              ? lcPool.length > 0
                ? drawQuestionSubset(
                    lcPool,
                    1,
                    3,
                    previousQuestionSubquestions?.[subquestionIndex]?.learning_content,
                  )
                : undefined
              : cfg.learning_content;
            const resolvedLp = redrawLp
              ? lpPool.length > 0
                ? drawQuestionSubset(
                    lpPool,
                    1,
                    2,
                    previousQuestionSubquestions?.[subquestionIndex]?.learning_performance,
                  )
                : undefined
              : cfg.learning_performance;
            if (redrawLc && resolvedLc?.length) {
              hasRedrawnSubquestion = true;
              questionPredrawnFields.push(lcAddress);
            }
            if (redrawLp && resolvedLp?.length) {
              hasRedrawnSubquestion = true;
              questionPredrawnFields.push(lpAddress);
            }
            questionSubquestionAutoFields.push({
              _lcWasAutoDrawn: redrawLc && !!resolvedLc?.length,
              _lpWasAutoDrawn: redrawLp && !!resolvedLp?.length,
            });
            if (historyQuestionParams) {
              return {
                ...cfg,
                ...(redrawLc ? { learning_content: resolvedLc } : {}),
                ...(redrawLp ? { learning_performance: resolvedLp } : {}),
              };
            }
            return {
              question_type: cfg.question_type || undefined,
              cognitive_process: subject === "social_studies" ? cfg.cognitive_process || undefined : undefined,
              instruction: cfg.instruction?.trim() || undefined,
              content_type: cfg.content_type || undefined,
              image_generation_mode: cfg.image_generation_mode || undefined,
              question_word_limit: cfg.question_word_limit,
              option_word_limit: cfg.option_word_limit,
              text_word_limit: cfg.text_word_limit,
              reporting_scale: subject === "natural_sciences" ? cfg.reporting_scale || undefined : undefined,
              learning_content: resolvedLc,
              learning_performance: resolvedLp,
            };
          })
        : [];
      builtSubquestionAutoFields.push(questionSubquestionAutoFields);
      builtPerQuestionAutoFields.push([
        ...(questionPredrawnFields.includes(seedAddress) ? ["seed"] : []),
        ...(randomStyle !== undefined ? ["style"] : []),
        ...(randomContentType !== undefined ? ["content_type"] : []),
        ...(randomContext !== undefined ? ["context"] : []),
        ...(randomSetType !== undefined ? ["set_type"] : []),
        ...(randomQuestionType !== undefined ? ["q_type"] : []),
        ...(randomSubjectFilter !== undefined ? ["subject_filter"] : []),
        ...(randomSubContext !== undefined ? ["sub_context"] : []),
        ...(randomScienceCompetency !== undefined ? ["science_competency"] : []),
        ...(redrawQuestionLp && questionLp?.length ? ["learning_performance"] : []),
        ...(redrawQuestionLc && questionLc?.length ? ["learning_content"] : []),
      ]);
      const historyQuestionRedraws = {
        ...(seedWasPredrawn ? { seed: resolvedSeed } : {}),
        ...(randomStyle !== undefined ? { style: randomStyle } : {}),
        ...(randomContentType !== undefined ? { content_type: randomContentType[0] } : {}),
        ...(randomContext !== undefined ? { context: randomContext } : {}),
        ...(randomSetType !== undefined ? { set_type: randomSetType[0] } : {}),
        ...(randomQuestionType !== undefined ? { q_type: randomQuestionType } : {}),
        ...(randomSubjectFilter !== undefined ? { subject_filter: randomSubjectFilter } : {}),
        ...(randomSubContext !== undefined ? { sub_context: randomSubContext[0] } : {}),
        ...(randomScienceCompetency !== undefined ? { science_competency: randomScienceCompetency } : {}),
        ...(redrawQuestionLp && questionLp?.length ? { learning_performance: questionLp } : {}),
        ...(redrawQuestionLc && questionLc?.length ? { learning_content: questionLc } : {}),
      };
      const result: Record<string, unknown> = historyQuestionParams
        ? { ...historyQuestionParams, ...historyQuestionRedraws }
        : {
            ...perQuestionBase,
            seed: resolvedSeed,
            style: randomStyle ?? (baseParams.style ? [baseParams.style] : undefined),
            content_type: randomContentType?.[0] ?? baseParams.content_type,
            context: randomContext ?? baseParams.context,
            set_type: randomSetType?.[0] ?? baseParams.set_type,
            q_type: randomQuestionType ?? baseParams.q_type,
            subject_filter: randomSubjectFilter ?? (baseParams.subject_filter ? [baseParams.subject_filter] : undefined),
            sub_context: randomSubContext?.[0] ?? baseParams.sub_context,
            science_competency: randomScienceCompetency ?? baseParams.science_competency,
            difficulty: subject !== "natural_sciences" ? (baseParams.difficulty ?? "medium") : undefined,
            model_plan: baseParams.model_plan ?? models?.defaults.plan,
            model_execute: baseParams.model_execute ?? models?.defaults.execute,
            // For verify/correct tiers, defaults.verify / defaults.correct are "" when unset.
            // Substituting "" would be wrong (it means "no override"). Only apply the default
            // when the base param is explicitly undefined (user made no selection) AND the
            // server-configured default is actually a non-empty model id.
            model_verify: baseParams.model_verify ?? (models?.defaults.verify || undefined),
            model_correct: baseParams.model_correct ?? (models?.defaults.correct || undefined),
            // For tier effort levels, "" means "inherit 出題 Effort" — never send it.
            // Use the server-configured effort default only when it is actually non-empty.
            effort_verify: baseParams.effort_verify ?? (models?.defaults.effort_verify || undefined),
            effort_correct: baseParams.effort_correct ?? (models?.defaults.effort_correct || undefined),
            learning_performance: questionLp,
            learning_content: questionLc,
          };
      if (
        (shouldSendSubquestionConfigs || !!historyQuestionParams) &&
        questionSubquestionConfigs.length > 0 &&
        (!historyQuestionParams || Object.keys(historyQuestionRedraws).length > 0 || hasRedrawnSubquestion)
      ) {
        result.subquestion_configs = JSON.stringify(questionSubquestionConfigs);
      }
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
      predrawnFields.push(...questionPredrawnFields);
      return result;
    });
    const perQuestionParams: Record<string, unknown>[] = preserveHistoryPerQuestionParams
      ? historyPerQuestionParams
      : buildPerQuestionParams();
    const usingHistoryPerQuestionParams = preserveHistoryPerQuestionParams;
    setPendingPerQuestionParams(perQuestionParams);
    setPendingResolvedSubquestionConfigs(
      usingHistoryPerQuestionParams
        ? perQuestionParams.map((params) =>
            parseSubquestionConfigs(params.subquestion_configs).map(() => ({})),
          )
        : builtSubquestionAutoFields,
    );
    setPerQuestionAutoFields(
      usingHistoryPerQuestionParams
        ? perQuestionParams.map(() => [])
        : builtPerQuestionAutoFields,
    );
    setPendingParams({
      ...baseParams,
      predrawn_fields: JSON.stringify(usingHistoryPerQuestionParams ? [] : predrawnFields),
      per_question_params: JSON.stringify(perQuestionParams),
    });
  }

  function handleConfirmSend() {
    if (!pendingParams) return;
    const submittedParams = pendingPerQuestionParams
      ? { ...pendingParams, per_question_params: JSON.stringify(pendingPerQuestionParams) }
      : pendingParams;
    // Renew the session concurrently — fire-and-forget, errors swallowed.
    // This covers the case where the form sat open long enough for the session
    // to drift toward expiry since the mount-time check ran.
    void renewSessionIfNeeded().catch(() => undefined);
    generationStartedRef.current = true;
    if (draftSaveTimeoutRef.current !== null) {
      window.clearTimeout(draftSaveTimeoutRef.current);
      draftSaveTimeoutRef.current = null;
    }
    if (userId) clearDraft(userId);
    setPendingParams(null);
    setPendingPerQuestionParams(null);
    onSubmit(submittedParams);
  }

  function updatePendingSubquestionInstruction(
    questionIndex: number,
    subquestionIndex: number,
    instruction: string,
  ) {
    setPendingPerQuestionParams((current) => {
      const perQuestionParams = current ?? parsePerQuestionParams(pendingParams?.per_question_params);
      const questionParams = perQuestionParams[questionIndex];
      if (!questionParams) return current;
      const configs = parseSubquestionConfigs(questionParams.subquestion_configs);
      if (!configs[subquestionIndex]) return current;
      const normalizedInstruction = instruction.trim() || undefined;
      const nextConfigs = configs.map((config, index) =>
        index === subquestionIndex
          ? serialisableSubquestionConfig({ ...config, instruction: normalizedInstruction })
          : config,
      );
      const nextPerQuestionParams = perQuestionParams.map((params, index) =>
        index === questionIndex
          ? { ...params, subquestion_configs: JSON.stringify(nextConfigs) }
          : params,
      );
      return nextPerQuestionParams;
    });
  }

  if (pendingParams) {
    const p = pendingParams;
    const resolvedPerQuestionParams = pendingPerQuestionParams ?? (p.per_question_params
      ? JSON.parse(p.per_question_params) as Record<string, unknown>[]
      : []);
    const allLpEntries = schemas?.學習表現 ?? [];
    const allLcEntries = schemas?.學習內容 ?? [];
    const lcEntryByCode = new Map(allLcEntries.map((e) => [e.value, e]));
    const lpEntryByCode = new Map(allLpEntries.map((e) => [e.value, e]));

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
      { label: t("form.confirm_difficulty"), value: p.difficulty, subjects: ["math", "social_studies"], kind: "defaulted", defaultValue: "medium" },
      { label: t("form.confirm_reporting_scale"), value: p.reporting_scale, subjects: ["natural_sciences"], kind: "defaulted", defaultValue: t("form.confirm_random") },
      { label: t("form.confirm_subject_filter"), value: p.subject_filter, subjects: ["math", "social_studies"], kind: subject === "social_studies" ? "sampled" : "absent" },
      { label: t("form.confirm_content_domain"), value: p.content_domain, subjects: ["social_studies"], kind: "sampled" },
      { label: t("form.confirm_target_surface"), value: p.target_surface ?? "紙本", subjects: ["social_studies"] },
      { label: t("form.confirm_count"), value: String(p.count), subjects: allSubjects },
      {
        label: t("form.confirm_coverage_mode"),
        value: subject === "social_studies" ? p.coverage_mode : undefined,
        subjects: ["social_studies"],
      },
      { label: t("form.confirm_passage"), value: p.passage, subjects: allSubjects },
      { label: t("form.confirm_options"), value: p.options?.join(", "), subjects: ["math"] },
      { label: t("form.confirm_text_word_limit"), value: p.text_word_limit !== undefined ? String(p.text_word_limit) : undefined, subjects: ["social_studies", "natural_sciences", ...(p.passage?.trim() ? [] : ["math"])], kind: "defaulted", defaultValue: t("form.confirm_unlimited") },
      { label: t("form.confirm_sub_question_count"), value: p.sub_question_count !== undefined ? String(p.sub_question_count) : undefined, subjects: ["social_studies", "math", "natural_sciences"] },
      { label: t("form.confirm_model_plan"), value: p.model_plan, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      { label: t("form.confirm_model_execute"), value: p.model_execute, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      { label: t("form.confirm_model_verify"), value: p.model_verify, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      { label: t("form.confirm_model_correct"), value: p.model_correct, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
      ...(models?.effort ? ([
        { label: t("form.confirm_effort_plan"), value: p.effort_plan, subjects: allSubjects, kind: "defaulted" as const, defaultValue: t("form.confirm_system_default") },
        { label: t("form.confirm_effort_execute"), value: p.effort_execute, subjects: allSubjects, kind: "defaulted" as const, defaultValue: t("form.confirm_system_default") },
        { label: t("form.confirm_effort_verify"), value: p.effort_verify, subjects: allSubjects, kind: "absent" as const },
        { label: t("form.confirm_effort_correct"), value: p.effort_correct, subjects: allSubjects, kind: "absent" as const },
      ] satisfies ConfirmationRow[]) : []),
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
      {
        label: t("form.confirm_core_question_callback"),
        value: p.core_question_callback ? t("form.confirm_yes") : undefined,
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
              _lcWasAutoDrawn: pendingResolvedSubquestionConfigs[index]?.[subquestionIndex]?._lcWasAutoDrawn,
              _lpWasAutoDrawn: pendingResolvedSubquestionConfigs[index]?.[subquestionIndex]?._lpWasAutoDrawn,
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
                            {t("form.confirm_not_filled")}
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
                    <SubquestionConfigCards
                      configs={questionSubquestionConfigs}
                      subject={subject}
                      lcEntryByCode={lcEntryByCode}
                      lpEntryByCode={lpEntryByCode}
                      onInstructionChange={(subquestionIndex, instruction) =>
                        updatePendingSubquestionInstruction(index, subquestionIndex, instruction)
                      }
                    />
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
            onClick={() => {
              setPendingParams(null);
              setPendingPerQuestionParams(null);
            }}
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
    <form onSubmit={handleSubmit} onChange={markUnsubmittedInput} className="space-y-4">
      {draftToRestore && (showDraftPrompt || showDraftHistoryChoice) && (
        <section
          role={showDraftHistoryChoice ? "dialog" : "status"}
          aria-label={
            showDraftHistoryChoice
              ? t("form.draft_history_choice")
              : undefined
          }
          className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <p className="font-medium">
            {t(
              showDraftHistoryChoice
                ? "form.draft_history_choice"
                : "form.draft_found",
            )}
          </p>
          <p className="mt-1 text-amber-800">
            {t("form.draft_saved_at").replace(
              "{time}",
              formatDraftRelativeTime(draftToRestore.savedAt, lang),
            )}
            <span hidden aria-hidden="true">
              {new Date(draftToRestore.savedAt).toLocaleString(lang)}
            </span>
          </p>
          <DraftSummary
            fields={draftToRestore.fields}
            lang={lang}
            t={t}
            subject={subject}
            schemas={schemas}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleRestoreDraft}
              className="rounded bg-amber-700 px-3 py-1.5 font-medium text-white hover:bg-amber-800"
            >
              {t("form.draft_restore")}
            </button>
            {showDraftHistoryChoice ? (
              <>
                <button
                  type="button"
                  onClick={handleUseHistoryParams}
                  className="rounded border border-amber-400 bg-white px-3 py-1.5 font-medium text-amber-900 hover:bg-amber-100"
                >
                  {t("form.draft_use_history")}
                </button>
                <button
                  type="button"
                  onClick={handleStartWithDefaults}
                  className="rounded border border-amber-300 bg-white px-3 py-1.5 font-medium text-amber-900 hover:bg-amber-100"
                >
                  {t("form.draft_restart")}
                </button>
              </>
            ) : (
              <div>
                <button
                  type="button"
                  onClick={handleRestartDraft}
                  className="rounded border border-amber-300 bg-white px-3 py-1.5 font-medium text-amber-900 hover:bg-amber-100"
                >
                  {t("form.draft_restart")}
                </button>
                <p className="mt-1 max-w-64 text-xs text-amber-800">
                  {t("form.draft_discard_warning")}
                </p>
              </div>
            )}
          </div>
        </section>
      )}
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
      {pinRuleViolations.length > 0 && (
        <div role="status" className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          <p>⚠ {t("form.pin_rule_warning_title")}</p>
          <ul className="mt-1 list-disc pl-5">
            {pinRuleViolations.map((violation) => (
              <li key={violation}>{t(PIN_RULE_MESSAGE_KEYS[violation])}</li>
            ))}
          </ul>
        </div>
      )}
      {surfaceQuestionTypeNotice.length > 0 && (
        <div role="status" className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          {t("form.digital_only_pin_cleared").replace("{types}", surfaceQuestionTypeNotice.join("、"))}
        </div>
      )}
      {isCurriculumSubject && (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{t("form.topic_label")}</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => {
              setField("topic", e.target.value);
              setField("coreQuestion", null);
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
              onPick={(q) => setField("coreQuestion", q)}
              onClear={() => setField("coreQuestion", null)}
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
          onChange={(e) => setField("grade", Number(e.target.value))}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          {schemas.grades.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </div>

      {subject === "natural_sciences" ? (
        <div>
          <label htmlFor="reporting_scale" className="block text-sm font-medium">
            {t("form.reporting_scale")}
          </label>
          <select
            id="reporting_scale"
            value={reportingScale}
            onChange={(e) => setField("reportingScale", e.target.value)}
            className="mt-1 block w-full border rounded px-2 py-1"
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
      ) : (
        <div>
          <label htmlFor="difficulty" className="block text-sm font-medium">
            {t("form.difficulty")}
          </label>
          <select
            id="difficulty"
            value={difficulty}
            onChange={(e) => setField("difficulty", e.target.value as "" | "easy" | "medium" | "hard")}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="">{t("form.difficulty_default")}</option>
            <option value="easy">{t("form.difficulty_easy")}</option>
            <option value="medium">{t("form.difficulty_medium")}</option>
            <option value="hard">{t("form.difficulty_hard")}</option>
          </select>
        </div>
      )}

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
              setField("subjectFilter", e.target.value);
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

      {subject === "social_studies" && (schemas.內容領域 ?? []).length > 0 && (
        <div>
          <label htmlFor="content-domain-select" className="block text-sm font-medium">
            {t("form.content_domain")}
          </label>
          <select
            id="content-domain-select"
            value={contentDomain ?? ""}
            onChange={(e) => {
              markUserChosen("content_domain");
              setField("contentDomain", e.target.value);
            }}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="">{t("form.content_domain_random")}</option>
            {(schemas.內容領域 ?? []).map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.value}
              </option>
            ))}
          </select>
        </div>
      )}

      {subject === "social_studies" && (
        <div>
          <label htmlFor="target-surface-select" className="block text-sm font-medium">
            {t("form.target_surface")}
          </label>
          <select
            id="target-surface-select"
            value={targetSurface ?? "紙本"}
            onChange={(e) => {
              const nextSurface = e.target.value as "紙本" | "數位";
              setField("targetSurface", nextSurface);
              if (nextSurface === "數位") setSurfaceQuestionTypeNotice([]);
            }}
            className="mt-1 block w-full border rounded px-2 py-1"
          >
            <option value="紙本">紙本</option>
            <option value="數位">數位</option>
          </select>
        </div>
      )}

      {Array.isArray(schemas.學習表現) && schemas.學習表現.length > 0 && (
        <div>
          <div className="flex items-center justify-between">
            <label className="block text-sm font-medium">{t("form.learning_performance")}</label>
            <button
              type="button"
              onClick={() => {
                setUseCurriculumSearch((v) => !v);
                markUnsubmittedInput();
              }}
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
                    setField("learningPerformance", values);
                    markUnsubmittedInput();
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
                        setField("learningPerformance", (prev) => toggleMulti(prev, entry.value));
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
              setField("style", e.target.value);
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
              setField("contentType", e.target.value);
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
              aria-label={t("form.custom_content_type")}
              value={customContentType}
              onChange={(e) => setField("customContentType", e.target.value)}
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
              setField("imageGenerationMode", e.target.value as "html" | "gpt_image")
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
                    setField("context", (prev) => toggleMulti(prev, s.value));
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
                setField("context", e.target.value ? [e.target.value] : []);
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
                setField("subContext", e.target.value);
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
            setField("setType", e.target.value);
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
                  setField("qType", (prev) => toggleMulti(prev, s.value));
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
                    setField("scienceCompetency", (prev) => toggleMulti(prev, s.value));
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

      {Array.isArray(schemas.學習內容) && schemas.學習內容.length > 0 && (
        <div>
          <div className="flex items-center justify-between">
            <label className="block text-sm font-medium">{t("form.learning_content")}</label>
            <button
              type="button"
              onClick={() => {
                setUseCurriculumSearch((v) => !v);
                markUnsubmittedInput();
              }}
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
                    setField("learningContent", values);
                    markUnsubmittedInput();
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
                        setField("learningContent", (prev) => toggleMulti(prev, entry.value));
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
        <label htmlFor="param-form-count" className="block text-sm font-medium">{t("form.count")}</label>
        <input
          id="param-form-count"
          type="number"
          min={1}
          max={10}
          value={count}
          onChange={(e) => setField("count", Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
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
            onChange={(e) => setField("coverageMode", e.target.value as "balanced" | "random")}
            className="mt-1 block w-64 border rounded px-2 py-1"
          >
            <option value="balanced">{t("form.coverage_mode.balanced")}</option>
            <option value="random">{t("form.coverage_mode.random")}</option>
          </select>
        </div>
      )}

      {(subject === "social_studies" || subject === "math" || subject === "natural_sciences") && (
        <div className="space-y-4 rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700">子題設定</h3>
          <div className="max-w-40">
            <div>
              <label htmlFor="param-form-sub-question-count" className="block text-sm font-medium">
                {t("form.confirm_sub_question_count")}
              </label>
              <input
                id="param-form-sub-question-count"
                type="number"
                min={3}
                max={7}
                value={subQuestionCount}
                onChange={(e) => {
                  const v = e.target.value;
                  setField("subQuestionCount", v === "" ? "" : Math.min(7, Math.max(3, Number(v) || 3)));
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
                  <SubQuestionConfigEditor
                    config={cfg}
                    subject={subject}
                    questionTypes={availableQuestionTypes}
                    cognitiveProcesses={subject === "social_studies" ? schemas.認知歷程 ?? [] : []}
                    contentTypes={schemas.題目內容類型 ?? []}
                    onChange={(patch) => updateSubquestionConfig(i, patch)}
                  />
                  <SubQuestionCurriculumPickers
                    availableLearningPerformance={availableLearningPerformance}
                    availableLearningContent={availableLearningContent}
                    learningPerformance={cfg.learning_performance}
                    learningContent={cfg.learning_content}
                    onLearningPerformanceChange={(values) =>
                      updateSubquestionConfig(i, { learning_performance: values })
                    }
                    onLearningContentChange={(values) =>
                      updateSubquestionConfig(i, { learning_content: values })
                    }
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {canUseTextWordLimit && (
        <div>
          <label htmlFor="text-word-limit" className="block text-sm font-medium">{t("form.text_word_limit")}</label>
          <input
            id="text-word-limit"
            type="number"
            min={1}
            value={textWordLimit ?? ""}
            onChange={(e) => setField("textWordLimit", e.target.value ? Number(e.target.value) : null)}
            placeholder={t("form.unlimited")}
            className="mt-1 block w-full border rounded px-2 py-1"
          />
        </div>
      )}

      {hasUserAuthoredMathPassage && (
        <p role="note" className="text-sm text-gray-500">
          {t("form.math_text_word_limit_unavailable")}
        </p>
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
                      setField("options", (prev) => prev.map((v, j) => j === i ? "" : v));
                    }
                  }}
                  onBlur={() => {
                    if (options[i] === "") {
                      setField("options", (prev) => prev.map((v, j) => j === i ? OPTION_HINT : v));
                    }
                  }}
                  onChange={(e) => {
                    const v = e.target.value;
                    setField("options", (prev) => prev.map((x, j) => j === i ? v : x));
                  }}
                  className="flex-1 border rounded px-2 py-1"
                />
                <button
                  type="button"
                  onClick={() => {
                    setField("options", (prev) => prev.filter((_, j) => j !== i));
                    markUnsubmittedInput();
                  }}
                  className="text-sm text-red-600 hover:underline disabled:opacity-40"
                  disabled={options.length <= 2}
                >−</button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => {
                setField("options", (prev) => [...prev, OPTION_HINT]);
                markUnsubmittedInput();
              }}
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
          onChange={(e) => setField("skipVerify", e.target.checked)}
        />
        <span className="text-sm">{t("form.skip_verify")}</span>
      </label>

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={disableReferenceFewshot}
            onChange={(e) => setField("disableReferenceFewshot", e.target.checked)}
          />
          <span className="text-sm">{t("form.disable_reference_fewshot")}</span>
        </label>
      )}

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={coreQuestionCallback}
            onChange={(e) => setField("coreQuestionCallback", e.target.checked)}
          />
          <span className="text-sm">{t("form.core_question_callback")}</span>
        </label>
      )}

      {isCurriculumSubject && topic.trim() && !coreQuestion && (
        <p role="status" className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          ⚠ {t("form.topic_no_pick_warning")}
        </p>
      )}

      {models && models.allowed.length > 0 && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
              <span>{t("params.model_plan_label")}</span>
              <select
                aria-label={t("params.model_plan_label")}
                value={modelPlan}
                onChange={(e) => {
                  const newModel = e.target.value;
                  setField("modelPlan", newModel);
                  if (models.effort) {
                    const levels = newModel ? (models.effort[newModel] ?? []) : [];
                    setField("effortPlan", (prev) =>
                      levels.length === 0 || levels.includes(prev) ? prev : "medium",
                    );
                  }
                }}
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
            {planEffortLevels.length > 0 && (
              <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
                <span>{t("form.effort_plan")}</span>
                <select
                  aria-label={t("form.effort_plan")}
                  value={effortPlan}
                  onChange={(e) => setField("effortPlan", e.target.value)}
                  className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
                >
                  {planEffortLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="flex gap-2">
            <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
              <span>{t("params.model_execute_label")}</span>
              <select
                aria-label={t("params.model_execute_label")}
                value={modelExecute}
                onChange={(e) => {
                  const newModel = e.target.value;
                  setField("modelExecute", newModel);
                  if (models.effort) {
                    const levels = newModel ? (models.effort[newModel] ?? []) : [];
                    setField("effortExecute", (prev) =>
                      levels.length === 0 || levels.includes(prev) ? prev : "medium",
                    );
                  }
                }}
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
            {executeEffortLevels.length > 0 && (
              <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
                <span>{t("form.effort_execute")}</span>
                <select
                  aria-label={t("form.effort_execute")}
                  value={effortExecute}
                  onChange={(e) => setField("effortExecute", e.target.value)}
                  className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
                >
                  {executeEffortLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="flex gap-2">
            <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
              <span>{t("params.model_verify_label")}</span>
              <select
                aria-label={t("params.model_verify_label")}
                value={modelVerify}
                onChange={(e) => {
                  const newModel = e.target.value;
                  setField("modelVerify", newModel);
                  if (models.effort) {
                    // Effective model after change: newModel || modelExecute || defaults.execute
                    const effectiveModel = newModel || modelExecute || models.defaults.execute;
                    const levels = effectiveModel ? (models.effort[effectiveModel] ?? []) : [];
                    setField("effortVerify", (prev) =>
                      prev === "" || levels.length === 0 || levels.includes(prev) ? prev : "",
                    );
                  }
                }}
                className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
              >
                <option value="">
                  {models.defaults.verify
                    ? `${t("params.model_follow_execute_option")} (${models.defaults.verify})`
                    : t("params.model_follow_execute_option")}
                </option>
                {models.allowed.map((m) => (
                  <option key={`verify-${m}`} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            {verifyEffortLevels.length > 0 && (
              <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
                <span>{t("form.effort_verify")}</span>
                <select
                  aria-label={t("form.effort_verify")}
                  value={effortVerify}
                  onChange={(e) => setField("effortVerify", e.target.value)}
                  className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
                >
                  <option value="">
                    {models.defaults.effort_verify
                      ? `${t("form.effort_follow_execute_option")} (${models.defaults.effort_verify})`
                      : t("form.effort_follow_execute_option")}
                  </option>
                  {verifyEffortLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="flex gap-2">
            <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
              <span>{t("params.model_correct_label")}</span>
              <select
                aria-label={t("params.model_correct_label")}
                value={modelCorrect}
                onChange={(e) => {
                  const newModel = e.target.value;
                  setField("modelCorrect", newModel);
                  if (models.effort) {
                    // Effective model after change: newModel || modelExecute || defaults.execute
                    const effectiveModel = newModel || modelExecute || models.defaults.execute;
                    const levels = effectiveModel ? (models.effort[effectiveModel] ?? []) : [];
                    setField("effortCorrect", (prev) =>
                      prev === "" || levels.length === 0 || levels.includes(prev) ? prev : "",
                    );
                  }
                }}
                className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
              >
                <option value="">
                  {models.defaults.correct
                    ? `${t("params.model_follow_execute_option")} (${models.defaults.correct})`
                    : t("params.model_follow_execute_option")}
                </option>
                {models.allowed.map((m) => (
                  <option key={`correct-${m}`} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            {correctEffortLevels.length > 0 && (
              <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
                <span>{t("form.effort_correct")}</span>
                <select
                  aria-label={t("form.effort_correct")}
                  value={effortCorrect}
                  onChange={(e) => setField("effortCorrect", e.target.value)}
                  className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
                >
                  <option value="">
                    {models.defaults.effort_correct
                      ? `${t("form.effort_follow_execute_option")} (${models.defaults.effort_correct})`
                      : t("form.effort_follow_execute_option")}
                  </option>
                  {correctEffortLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
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
