import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getAvailableModels, planCoreQuestions, previewGenerate, resolveGenerate, type AvailableModels, type PromptPreview, type SchemaEntry, type Schemas } from "../api/client";
import { useT } from "../i18n/useT";
import { clearDraft, loadDraft, saveDraft, type FormDraft } from "../lib/formDraft";
import { filterEntriesByAdmittedParent } from "../lib/admittedBy";
import { fetchCurriculumPool, type CurriculumPool } from "../lib/curriculumPool";
import {
  filterDrawnAfterSubquestionCountRedraw,
  rebuildSubquestionSlots,
} from "../lib/rebuildSubquestionSlots";
import { renewSessionIfNeeded } from "../lib/sessionRenewal";
import { exportFormWorkspace } from "../lib/workspace/adapters/formWorkspace";
import { exportConfirmationWorkspace } from "../lib/workspace/adapters/confirmationWorkspace";
import type { ConfirmationWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import { useSurfaceParticipation } from "../lib/workspace/useSurfaceParticipation";
import { useWorkspaceStore, type OperationHandle, type SurfaceParticipation, type SurfaceReadiness } from "../lib/workspace/workspaceStore";
import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import {
  findSocialStudiesPinRuleViolations,
  type SocialStudiesPinRuleViolation,
} from "../utils/socialStudiesPinRules";
import CoreQuestionPicker from "./CoreQuestionPicker";
import SubQuestionConfigEditor from "./SubQuestionConfigEditor";
import SubQuestionCurriculumPickers, { SearchPicker } from "./SubQuestionCurriculumPickers";
import SubquestionConfigCards, { type ResolvedSubQuestionConfig } from "./SubquestionConfigCards";
import DrawnValueRows from "./DrawnValueRows";
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
  reporting_scale?: string;
  /** Per-小題 圖像種類 pin (free text; canonical values suggested via datalist). ADR 0015. */
  figure_kind?: string;
  learning_content?: string[];
  learning_performance?: string[];
}

function parseSubquestionConfigs(value: unknown): SubQuestionConfig[] {
  const parsed = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? (() => {
          try {
            return JSON.parse(value) as unknown;
          } catch {
            return null;
          }
        })()
      : null;
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (row): row is SubQuestionConfig => typeof row === "object" && row !== null && !Array.isArray(row),
  );
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

function normaliseResolvedPerQuestionParams(
  rows: Record<string, unknown>[],
): Record<string, unknown>[] {
  return rows.map((row) => Array.isArray(row.subquestion_configs)
    ? { ...row, subquestion_configs: JSON.stringify(row.subquestion_configs) }
    : row);
}

function serialisableSubquestionConfig(config: SubQuestionConfig): SubQuestionConfig {
  return Object.fromEntries(
    Object.entries(config).filter(([key, value]) => value !== undefined && key !== "text_word_limit"),
  ) as SubQuestionConfig;
}

function mergeLiveSubquestionConfigs(
  historyValue: unknown,
  liveConfigs: readonly SubQuestionConfig[],
  editedFields: ReadonlyMap<number, ReadonlySet<keyof SubQuestionConfig>>,
  replaceHistory: boolean,
): string {
  const historyConfigs = parseSubquestionConfigs(historyValue);
  const historyHasValues = historyConfigs.some((config) => Object.keys(config).length > 0);
  const rowCount = Math.max(historyConfigs.length, liveConfigs.length);
  const mergedConfigs = Array.from({ length: rowCount }, (_, index) => {
    const historyConfig = historyConfigs[index] ?? {};
    const liveConfig = liveConfigs[index] ?? {};
    if (replaceHistory || !historyHasValues) {
      return serialisableSubquestionConfig(liveConfig);
    }

    const merged = { ...historyConfig } as Record<string, unknown>;
    for (const field of editedFields.get(index) ?? []) {
      if (Object.hasOwn(liveConfig, field)) merged[field] = liveConfig[field];
      else delete merged[field];
    }
    return serialisableSubquestionConfig(merged as SubQuestionConfig);
  });
  return JSON.stringify(mergedConfigs);
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
  // Exposed per-subquestion inside subquestion_configs, not at top level.
  | "question_word_limit"
  // Exposed per-subquestion inside subquestion_configs, not at top level.
  | "option_word_limit"
  // Not exposed in the form UI, but the resolver completes and the generation
  // wire must preserve it verbatim.
  | "core_competency"
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
  // The controls send a single string; confirmed resolver payloads already carry arrays.
  style?: string | string[];
  // The controls send a single string; confirmed resolver payloads already carry arrays.
  subject_filter?: string | string[];
  // History records carry their seed even though the form does not edit it.
  seed?: number;
  // Resolver-completed hidden field carried through confirmation.
  core_competency?: string[];
};

export interface ParamFormProps {
  subject?: string;
  onSubmit: (params: FormParams) => void;
  disabled: boolean;
  initialParams?: Partial<FormParams> & { [key: string]: unknown };
  onUnsubmittedInput?: () => void;
  /** When present, takes precedence over loadDraft and history prefill (issue #772). */
  recoveredForm?: import("../lib/workspace/adapters/types").FormWorkspaceSnapshot;
  /** When present, reopens the exact settled pre-send confirmation (issue #773). */
  recoveredConfirmation?: ConfirmationWorkspaceSnapshot;
  /** Return false to keep the banner when result evidence has not hydrated. */
  onRecoveryAcknowledge?: () => boolean | void;
  /** Called when the user clicks 捨棄 on the recovery banner (issue #772). */
  onRecoveryDiscard?: () => boolean | void;
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
  textInstruction: string;
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
  /** Request-level kill-switch for ADR 0015 distinct-kind guarantee. Issue #450. */
  allowDuplicateFigureKinds: boolean;
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

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
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

function ConfirmationRowActions({
  isRandom,
  editor,
  onRedraw,
  editLabel,
  redrawLabel,
}: {
  isRandom: boolean;
  editor?: () => ReactNode;
  onRedraw?: () => void;
  editLabel: ReactNode;
  redrawLabel: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  if (!isRandom || (editor === undefined && onRedraw === undefined)) return null;
  return (
    <span className="ml-3 inline-flex flex-wrap items-center gap-1">
      {editor !== undefined && !editing && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          {editLabel}
        </button>
      )}
      {onRedraw !== undefined && (
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            onRedraw();
          }}
          className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
        >
          {redrawLabel}
        </button>
      )}
      {editing && editor?.()}
    </span>
  );
}

function confirmationEntries(
  entries: readonly SchemaEntry[],
  current: string | readonly string[] | undefined,
): SchemaEntry[] {
  const values = typeof current === "string" ? [current] : current ?? [];
  const known = new Set(entries.map((entry) => entry.value));
  return [
    ...entries,
    ...values
      .filter((value) => value !== "" && !known.has(value))
      .map((value) => ({ value, instruction: "" })),
  ];
}

function entriesForValues(
  entries: readonly SchemaEntry[],
  values: readonly string[],
): SchemaEntry[] {
  const byValue = new Map(entries.map((entry) => [entry.value, entry]));
  return values.map((value) => byValue.get(value) ?? { value, instruction: "" });
}

function ConfirmationSingleSelect({
  label,
  value,
  entries,
  onChange,
}: {
  label: string;
  value: unknown;
  entries: readonly SchemaEntry[];
  onChange: (value: string) => void;
}) {
  return (
    <select
      aria-label={label}
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange(event.currentTarget.value)}
      className="rounded border border-gray-300 bg-white px-2 py-1 text-sm"
    >
      <option value="">未填寫</option>
      {confirmationEntries(entries, typeof value === "string" ? value : undefined).map((entry) => (
        <option key={entry.value} value={entry.value}>{entry.value}</option>
      ))}
    </select>
  );
}

function ConfirmationMultiSelect({
  label,
  value,
  entries,
  max,
  onChange,
}: {
  label: string;
  value: unknown;
  entries: readonly SchemaEntry[];
  max: number;
  onChange: (value: string[]) => void;
}) {
  const selected = Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
  return (
    <select
      multiple
      aria-label={label}
      value={selected}
      onChange={(event) => onChange(
        Array.from(event.currentTarget.selectedOptions)
          .map((option) => option.value)
          .slice(0, max),
      )}
      className="min-w-48 rounded border border-gray-300 bg-white px-2 py-1 text-sm"
      size={Math.min(4, Math.max(2, entries.length))}
    >
      {confirmationEntries(entries, selected).map((entry) => (
        <option key={entry.value} value={entry.value}>{entry.value}</option>
      ))}
    </select>
  );
}

function ConfirmationSubQuestionCountInput({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: number) => void;
}) {
  return (
    <input
      aria-label="小題數"
      type="number"
      min={3}
      max={7}
      value={typeof value === "number" ? value : ""}
      onChange={(event) => onChange(Number(event.currentTarget.value))}
      className="w-24 rounded border border-gray-300 bg-white px-2 py-1 text-sm"
    />
  );
}

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
                        contentDomain={fields.contentDomain}
                        questionTypes={schemas?.題型 ?? []}
                        contentTypes={schemas?.題目內容類型 ?? []}
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
      ? filterEntriesByAdmittedParent(
          schemas.情境子類別 ?? [],
          "情境",
          firstContext,
        )[0]?.value ?? ""
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
    textInstruction: "",
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
    allowDuplicateFigureKinds: false,
  };
}

const ICCS_DOMAIN_FILTER_SUBJECTS = new Set(["公民與社會", "跨科"]);
const RESOLVER_FIELD_ALIASES: Record<string, string> = {
  context: "情境",
  set_type: "題型種類",
  q_type: "題型",
  content_type: "題目內容類型",
  subject_filter: "科目",
  content_domain: "內容領域",
  sub_context: "情境子類別",
  science_competency: "科學能力",
  learning_content: "學習內容",
  learning_performance: "學習表現",
  core_competency: "核心素養",
  math_thinking: "數學思考",
  sub_question_count: "sub_question_count",
};

const RESOLVER_VALUE_ALIASES: Record<string, string> = {
  "情境": "context",
  "題型種類": "set_type",
  "題型": "q_type",
  "題目內容類型": "content_type",
  "數學思考": "math_thinking",
  "科目": "subject_filter",
  "內容領域": "content_domain",
  "情境子類別": "sub_context",
  "科學能力": "science_competency",
  "學習內容": "learning_content",
  "學習表現": "learning_performance",
  "核心素養": "core_competency",
  "認知歷程": "cognitive_process",
};

function resolverDrewField(drawns: readonly string[], index: number, key: string): boolean {
  const prefix = `per_question_params[${index}].`;
  const canonical = RESOLVER_FIELD_ALIASES[key] ?? key;
  return drawns.includes(`${prefix}${key}`) || drawns.includes(`${prefix}${canonical}`) ||
    (index === 0 && (drawns.includes(key) || drawns.includes(canonical)));
}

function readConfirmationPathValue(
  path: string,
  root: Record<string, unknown>,
  perQuestionParams: Record<string, unknown>[],
): unknown {
  const match = path.match(/^per_question_params\[(\d+)\]\.(.+)$/);
  const localPath = match ? match[2] : path;
  const readFrom = (source: Record<string, unknown> | undefined): unknown => {
    if (!source) return undefined;
    const tokens = localPath.match(/[^.[\]]+|\[\d+\]/g) ?? [];
    let current: unknown = source;
    for (const token of tokens) {
      if (typeof current === "string") {
        try {
          current = JSON.parse(current) as unknown;
        } catch {
          return undefined;
        }
      }
      if (token.startsWith("[")) {
        if (!Array.isArray(current)) return undefined;
        current = current[Number(token.slice(1, -1))];
        continue;
      }
      if (!current || typeof current !== "object") return undefined;
      const record = current as Record<string, unknown>;
      const key = Object.hasOwn(record, token) ? token : RESOLVER_VALUE_ALIASES[token];
      current = key === undefined ? undefined : record[key];
    }
    return current;
  };
  const rowValue = match ? readFrom(perQuestionParams[Number(match[1])]) : undefined;
  return rowValue === undefined ? readFrom(root) : rowValue;
}

const CONFIRMATION_PARENT_CHILDREN: Record<string, string[]> = {
  "情境": ["情境子類別"],
  "科目": ["學習內容", "學習表現"],
  "內容領域": ["學習內容", "學習表現"],
  sub_question_count: ["subquestion_configs"],
};

function localConfirmationPath(path: string, index: number): string | undefined {
  const prefix = `per_question_params[${index}].`;
  if (path.startsWith(prefix)) return path.slice(prefix.length);
  if (index === 0 && !path.startsWith("per_question_params[")) return path;
  return undefined;
}

function isConfirmationChildPath(
  path: string,
  index: number,
  children: readonly string[],
): boolean {
  const local = localConfirmationPath(path, index);
  if (!local) return false;
  const slotField = local.match(/^subquestion_configs\[\d+\]\.(.+)$/)?.[1];
  const slotCanonical = slotField === undefined
    ? undefined
    : RESOLVER_FIELD_ALIASES[slotField] ?? slotField;
  return children.some((child) => child === "subquestion_configs"
    ? local.startsWith("subquestion_configs[")
    : local === child || local.startsWith(`${child}.`)
      || slotCanonical === child || slotCanonical?.startsWith(`${child}.`));
}

function clearConfirmationPath(
  row: Record<string, unknown>,
  path: string,
  index: number,
): void {
  const local = localConfirmationPath(path, index);
  if (!local) return;
  const configMatch = local.match(/^subquestion_configs\[(\d+)\]\.(.+)$/);
  if (configMatch) {
    const configs = parseSubquestionConfigs(row.subquestion_configs);
    const configIndex = Number(configMatch[1]);
    const field = configMatch[2];
    if (configs[configIndex]) {
      const key = RESOLVER_VALUE_ALIASES[field] ?? field;
      const config = configs[configIndex] as Record<string, unknown>;
      delete config[key];
      if (field === "認知歷程" || field === "cognitive_process") {
        delete config.cognitive_process;
        delete config["認知歷程"];
      }
      row.subquestion_configs = JSON.stringify(configs);
    }
    return;
  }
  const key = RESOLVER_VALUE_ALIASES[local] ?? local;
  // A batch worker inherits the top-level payload before applying this row.
  // Null therefore means "clear this row's inherited value"; deleting the key
  // would accidentally leave the old parent value in the worker payload.
  row[key] = null;
}

function filterCurriculumEntriesBySubject<T extends SchemaEntry>(
  entries: readonly T[],
  subject: string,
  resolvedSubject: string | readonly string[] | undefined,
  allSubjectValues: readonly string[],
): T[] {
  if (subject !== "math" && subject !== "social_studies") return [...entries];
  const values = typeof resolvedSubject === "string"
    ? resolvedSubject ? [resolvedSubject] : allSubjectValues
    : resolvedSubject && resolvedSubject.length > 0
      ? resolvedSubject
      : allSubjectValues;
  return filterEntriesByAdmittedParent(entries, "科目", values);
}

function filterLearningContentEntriesByDomain<T extends SchemaEntry>(
  entries: readonly T[],
  subject: string,
  resolvedSubject: string | readonly string[] | undefined,
  contentDomain: string | undefined,
  contentDomainMapping: Record<string, string[]> | undefined,
): T[] {
  if (subject !== "social_studies" || !contentDomain) return [...entries];
  const subjectValues = typeof resolvedSubject === "string"
    ? resolvedSubject ? [resolvedSubject] : []
    : resolvedSubject ?? [];
  if (!subjectValues.some((value) => ICCS_DOMAIN_FILTER_SUBJECTS.has(value))) {
    return [...entries];
  }
  const domainTaggedEntries = entries.filter((entry) =>
    Object.hasOwn(entry.admitted_by ?? {}, "內容領域"),
  );
  const domainAdmittedEntries = new Set(
    filterEntriesByAdmittedParent(domainTaggedEntries, "內容領域", contentDomain),
  );
  const mappedCodes = new Set(
    Object.entries(contentDomainMapping ?? {})
      .filter(([, domains]) => domains.includes(contentDomain))
      .map(([code]) => code),
  );
  return entries.filter((entry) =>
    Object.hasOwn(entry.admitted_by ?? {}, "內容領域")
      ? domainAdmittedEntries.has(entry)
      : !isPublicSocialStudiesCode(entry.value) || mappedCodes.has(entry.value),
  );
}

function isPublicSocialStudiesCode(code: string): boolean {
  return code.startsWith("公");
}

const PIN_RULE_MESSAGE_KEYS: Record<SocialStudiesPinRuleViolation, string> = {
  knowing_defining_limit: "form.pin_rule.knowing_defining_limit",
  cross_subject_relate: "form.pin_rule.cross_subject_relate",
};

/**
 * Returns true when the server response contains a well-formed array of
 * prompt previews.  Extracted at module level so the debounced-refetch effect
 * and the retry handler share one copy (#446 — prevents predicate drift).
 */
function isValidPromptPreviewResponse(
  prompts: unknown,
): prompts is Array<{
  index: number;
  subquestion_index: number | undefined;
  system_prompt: string;
  user_prompt: string;
}> {
  return (
    Array.isArray(prompts) &&
    prompts.every(
      (prompt) =>
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
        typeof prompt?.user_prompt === "string",
    )
  );
}

/**
 * The planner endpoint promises three distinct, non-empty textual
 * candidates. Treat a malformed success body as a planning failure so the
 * confirmation screen can keep its generation-decides fallback.
 */
function selectPlannedCoreQuestion(candidates: unknown): string | undefined {
  if (!Array.isArray(candidates) || candidates.length !== 3) return undefined;
  const normalised = candidates.map((candidate) =>
    typeof candidate === "string" ? candidate.trim() : "",
  );
  if (
    normalised.some((candidate) => candidate.length === 0) ||
    new Set(normalised).size !== normalised.length
  ) {
    return undefined;
  }
  return normalised[0];
}

function ConfirmationParticipation({ exportWorkspace }: Pick<SurfaceParticipation, "exportWorkspace">) {
  useSurfaceParticipation("generate.confirmation", {
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace,
  });
  return null;
}

export default function ParamForm({
  subject = "math",
  onSubmit,
  disabled,
  initialParams,
  onUnsubmittedInput,
  recoveredForm,
  recoveredConfirmation,
  onRecoveryAcknowledge,
  onRecoveryDiscard,
}: ParamFormProps) {
  // Recovery props are a one-shot snapshot. Latching them prevents the store's
  // acknowledgement update (or a late hydration render) from rebuilding the
  // ordinary form or confirmation from defaults/history.
  const [recoverySource] = useState(() => ({
    form: recoveredForm,
    confirmation: recoveredConfirmation,
  }));
  const recoveryForm = recoverySource.form;
  const recoveryConfirmation = recoverySource.confirmation;
  const hasRecovery = recoveryForm !== undefined || recoveryConfirmation !== undefined;
  const generationStartedRef = useRef(false);
  // When recovering, treat the form as already user-edited so autosave/guards work.
  const hasUserEditedRef = useRef(recoveryForm !== undefined);
  const [hasUserEdited, setHasUserEdited] = useState(recoveryForm !== undefined);
  // Recovery banner state (issue #772)
  const [recoveryBannerDismissed, setRecoveryBannerDismissed] = useState(false);
  // Invalid recovered fields: populated after schemas/models load (issue #772)
  const [recoveredInvalidFields, setRecoveredInvalidFields] = useState<Set<string>>(new Set());
  const showRecoveryBanner = hasRecovery && !recoveryBannerDismissed;
  const markUnsubmittedInput = () => {
    generationStartedRef.current = false;
    hasUserEditedRef.current = true;
    setHasUserEdited(true);
    onUnsubmittedInput?.();
  };
  const t = useT();
  const lang = useLangStore((state) => state.lang);
  const [schemas, setSchemas] = useState<CurriculumPool | null>(null);
  const curriculumRequestSeq = useRef(0);
  const latestGradePoolSeq = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);
  const [surfaceQuestionTypeNotice, setSurfaceQuestionTypeNotice] = useState<string[]>([]);
  const [pendingParams, setPendingParams] = useState<FormParams | null>(() =>
    recoveryConfirmation ? cloneJson(recoveryConfirmation.pendingParams) : null,
  );
  const [pendingPerQuestionParams, setPendingPerQuestionParams] = useState<Record<string, unknown>[] | null>(() =>
    recoveryConfirmation?.pendingPerQuestionParams
      ? cloneJson(recoveryConfirmation.pendingPerQuestionParams)
      : null,
  );
  const [clearedPaths, setClearedPaths] = useState<string[]>(() =>
    recoveryConfirmation ? [...recoveryConfirmation.clearedPaths] : [],
  );
  const [hasPendingConfirmationEdits, setHasPendingConfirmationEdits] = useState(() =>
    recoveryConfirmation?.hasPendingConfirmationEdits ?? false,
  );
  const [resolverLoading, setResolverLoading] = useState(false);
  const [resolverError, setResolverError] = useState<string | null>(null);
  // Generic gate: keyed by "${questionIndex}-${subquestionIndex}-${field}". Any truthy entry disables 確認送出.
  const [confirmInvalidFields, setConfirmInvalidFields] = useState<Map<string, true>>(new Map());
  const [coreQuestionResolution, setCoreQuestionResolution] = useState<"idle" | "loading" | "generated" | "failed">(() =>
    recoveryConfirmation?.coreQuestionResolution ?? "idle",
  );
  const [promptPreviews, setPromptPreviews] = useState<PromptPreview[]>([]);
  const [models, setModels] = useState<AvailableModels | null>(null);
  const [modelsResolved, setModelsResolved] = useState(false);
  const [useCurriculumSearch, setUseCurriculumSearch] = useState<boolean>(true);
  // Restored confirmation state is display-only until a teacher explicitly
  // edits/resubmits a field. This guard suppresses both preview effects until
  // one of the edit handlers deliberately releases it.
  const restoredConfirmationEffectsSuppressedRef = useRef(recoveryConfirmation !== undefined);
  const previewRequestedRef = useRef(recoveryConfirmation !== undefined);
  const previewRefetchSeqRef = useRef(0);
  const [previewRefetchLoading, setPreviewRefetchLoading] = useState(false);
  // #446: per-題組 stale-preview tracking. Keyed by 題組 index.
  // When non-empty a retry control appears on each stale 題組.
  const [stalePreviewIndices, setStalePreviewIndices] = useState<Set<number>>(new Set());
  // Accumulates which 題組 indices were edited since the last refetch effect captured them.
  const pendingEditedIndicesRef = useRef<Set<number>>(new Set());
  const resolveRequestRef = useRef<{
    payload: Record<string, unknown>;
    redraws: Record<string, number>;
    rebuildSubquestionSlots: boolean;
  } | null>(null);
  const resolveRequestSeqRef = useRef(0);
  const resolveOperationRef = useRef<OperationHandle | null>(null);
  const redrawsRef = useRef<Record<string, number>>(
    recoveryConfirmation ? cloneJson(recoveryConfirmation.redraws) : {},
  );
  const pendingParamsRef = useRef<FormParams | null>(
    pendingParams ? cloneJson(pendingParams) : null,
  );
  const pendingPerQuestionParamsRef = useRef<Record<string, unknown>[] | null>(
    pendingPerQuestionParams ? cloneJson(pendingPerQuestionParams) : null,
  );
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const hasInitialParams =
    initialParams !== undefined && Object.keys(initialParams).length > 0;
  const initialPendingPrefill = (() => {
    if (recoveryConfirmation && Object.hasOwn(recoveryConfirmation, "pendingPrefill")) {
      return recoveryConfirmation.pendingPrefill === null
        ? null
        : cloneJson(recoveryConfirmation.pendingPrefill);
    }
    return hasInitialParams
      ? cloneJson(initialParams as Record<string, unknown>)
      : undefined;
  })();
  const pendingPrefillRef = useRef<Record<string, unknown> | null | undefined>(initialPendingPrefill);
  // When recovery is provided, suppress the draft prompt entirely (issues #772/#773).
  const [draftToRestore, setDraftToRestore] = useState<FormDraft | null>(() =>
    hasRecovery ? null : (userId ? loadDraft(userId) : null),
  );
  const [historyDraftChoice, setHistoryDraftChoice] = useState<
    "draft" | "history" | "defaults" | null
  >(() => recoveryConfirmation?.historyDraftChoice ?? null);

  const normalisedHistoryPrefill = useMemo(
    () => normaliseHistoryPrefill(subject, initialParams),
    [initialParams, subject],
  );
  const ip = normalisedHistoryPrefill.params;
  const userChosenFields = useRef(new Set(Object.keys(ip)));
  const editedSubquestionFieldsRef = useRef(
    new Map<number, Set<keyof SubQuestionConfig>>(),
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

  const [formFields, setFormFields] = useState<FormFields>(() => {
    // When a recovered form is present, use its fields directly (issues #772/#773).
    // This takes precedence over initialParams / localStorage defaults.
    if (recoveryForm) {
      // Defensively fill in every required FormFields key so that downstream
      // code (e.g. passage.trim()) never sees undefined even when the snapshot
      // was created with a minimal/partial fields object (issue #776 tests).
      const f = recoveryForm.fields;
      return {
        grade: typeof f.grade === "number" || f.grade === "" ? f.grade : "",
        style: typeof f.style === "string" ? f.style : "",
        contentType: typeof f.contentType === "string" ? f.contentType : DEFAULT_CONTENT_TYPE,
        customContentType: typeof f.customContentType === "string" ? f.customContentType : "",
        context: Array.isArray(f.context) ? f.context : [],
        setType: typeof f.setType === "string" ? f.setType : "",
        qType: Array.isArray(f.qType) ? f.qType : [],
        count: typeof f.count === "number" ? f.count : 1,
        coverageMode: f.coverageMode === "random" ? "random" : "balanced",
        skipVerify: typeof f.skipVerify === "boolean" ? f.skipVerify : false,
        disableReferenceFewshot: typeof f.disableReferenceFewshot === "boolean" ? f.disableReferenceFewshot : false,
        coreQuestionCallback: typeof f.coreQuestionCallback === "boolean" ? f.coreQuestionCallback : true,
        imageGenerationMode: f.imageGenerationMode === "html" || f.imageGenerationMode === "gpt_image" ? f.imageGenerationMode : "gpt_image",
        difficulty: f.difficulty === "easy" || f.difficulty === "medium" || f.difficulty === "hard" ? f.difficulty : "",
        reportingScale: typeof f.reportingScale === "string" ? f.reportingScale : "",
        subjectFilter: typeof f.subjectFilter === "string" ? f.subjectFilter : "",
        passage: typeof f.passage === "string" ? f.passage : TEXT_HINT,
        textWordLimit: typeof f.textWordLimit === "number" ? f.textWordLimit : null,
        textInstruction: typeof f.textInstruction === "string" ? f.textInstruction : "",
        options: Array.isArray(f.options) ? f.options : [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT],
        topic: typeof f.topic === "string" ? f.topic : "",
        coreQuestion: typeof f.coreQuestion === "string" || f.coreQuestion === null ? f.coreQuestion : null,
        subContext: typeof f.subContext === "string" ? f.subContext : "",
        scienceCompetency: Array.isArray(f.scienceCompetency) ? f.scienceCompetency : [],
        learningPerformance: Array.isArray(f.learningPerformance) ? f.learningPerformance : [],
        learningContent: Array.isArray(f.learningContent) ? f.learningContent : [],
        subQuestionCount: typeof f.subQuestionCount === "number" || f.subQuestionCount === "" ? f.subQuestionCount : "",
        subquestionConfigs: Array.isArray(f.subquestionConfigs) ? f.subquestionConfigs : [],
        contentDomain: f.contentDomain ?? "",
        targetSurface: f.targetSurface === "數位" ? "數位" : "紙本",
        modelPlan: typeof f.modelPlan === "string" ? f.modelPlan : "",
        modelExecute: typeof f.modelExecute === "string" ? f.modelExecute : "",
        modelVerify: typeof f.modelVerify === "string" ? f.modelVerify : "",
        modelCorrect: typeof f.modelCorrect === "string" ? f.modelCorrect : "",
        effortPlan: typeof f.effortPlan === "string" ? f.effortPlan : "",
        effortExecute: typeof f.effortExecute === "string" ? f.effortExecute : "",
        effortVerify: typeof f.effortVerify === "string" ? f.effortVerify : "",
        effortCorrect: typeof f.effortCorrect === "string" ? f.effortCorrect : "",
        allowDuplicateFigureKinds: typeof f.allowDuplicateFigureKinds === "boolean" ? f.allowDuplicateFigureKinds : false,
      };
    }
    return {
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
    textInstruction: stringFromInit("text_instruction", ""),
    options: fromInit<string[]>(
      "options",
      [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT],
    ),
    topic: fromInit<string>("topic", ""),
    coreQuestion: fromInit<string | null>("core_question", null),
    subContext: fromInit<string>("sub_context", ""),
    scienceCompetency: fromInit<string[]>("science_competency", []),
    learningPerformance: fromInit<string[]>("learning_performance", []),
    learningContent: fromInit<string[]>("learning_content", []),
    subQuestionCount: fromInit<number | "">("sub_question_count", ""),
    subquestionConfigs: subquestionConfigsFromInit(),
    contentDomain: stringFromInit("content_domain", ""),
    targetSurface: ip.target_surface === "數位" ? "數位" : "紙本",
    modelPlan: stringFromInit("model_plan", window.localStorage.getItem("model_plan") ?? ""),
    modelExecute: stringFromInit("model_execute", window.localStorage.getItem("model_execute") ?? ""),
    modelVerify: stringFromInit("model_verify", window.localStorage.getItem("model_verify") ?? ""),
    modelCorrect: stringFromInit("model_correct", window.localStorage.getItem("model_correct") ?? ""),
    effortPlan: stringFromInit("effort_plan", window.localStorage.getItem("effort_plan") ?? ""),
    effortExecute: stringFromInit("effort_execute", window.localStorage.getItem("effort_execute") ?? ""),
    effortVerify: stringFromInit("effort_verify", window.localStorage.getItem("effort_verify") ?? ""),
    effortCorrect: stringFromInit("effort_correct", window.localStorage.getItem("effort_correct") ?? ""),
    allowDuplicateFigureKinds: false,
    };
  });
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
    textInstruction,
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
    allowDuplicateFigureKinds,
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
        (!hasUserEditedRef.current || jsonDeepEqual(formSnapshot, defaultsSnapshotRef.current))
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

  // An ordinary form recovery remains restoring until acknowledged. A settled
  // confirmation recovery is deliberately saveable once hydration finishes;
  // #773 lifts the old #772 refusal for that independent workspace.
  const formReadiness: SurfaceReadiness = showRecoveryBanner && !recoveryConfirmation
    ? "restoring"
    : hasDraftHistoryConflict || showDraftPrompt
    ? "restoring"
    : schemas !== null && defaultsReady && modelsResolved ? "ready" : "hydrating";
  const exportForm = useCallback(() => exportFormWorkspace(formSnapshot), [formSnapshot]);
  useSurfaceParticipation("generate.form", {
    readiness: formReadiness,
    hasEditableState: hasUserEdited,
    hasReceivedResults: false,
    exportWorkspace: exportForm,
  });
  const exportConfirmation = useCallback(() => pendingParams === null ? null : exportConfirmationWorkspace({
    pendingParams,
    pendingPerQuestionParams,
    ...(pendingPrefillRef.current !== undefined
      ? { pendingPrefill: pendingPrefillRef.current }
      : {}),
    clearedPaths,
    redraws: redrawsRef.current,
    hasPendingConfirmationEdits,
    coreQuestionResolution,
    historyDraftChoice,
  }), [pendingParams, pendingPerQuestionParams, clearedPaths, hasPendingConfirmationEdits, coreQuestionResolution, historyDraftChoice]);

  function handleRestoreDraft() {
    if (!draftToRestore) return;
    const fields = draftToRestore.fields;
    pendingPrefillRef.current = cloneJson(fields as unknown as Record<string, unknown>);
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
    setHasUserEdited(false);
    setHistoryDraftChoice("history");
    pendingPrefillRef.current = hasInitialParams
      ? cloneJson(initialParams as Record<string, unknown>)
      : null;
    setDraftToRestore(null);
    if (defaultsSnapshotRef.current !== null) {
      restoreFormSnapshot(defaultsSnapshotRef.current);
    }
  }

  function handleStartWithDefaults() {
    if (!schemas) return;
    hasUserEditedRef.current = false;
    setHasUserEdited(false);
    setHistoryDraftChoice("defaults");
    pendingPrefillRef.current = null;
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
    if (
      restoredConfirmationEffectsSuppressedRef.current ||
      !pendingParams ||
      coreQuestionResolution === "loading" ||
      previewRequestedRef.current
    ) return;
    let cancelled = false;
    previewRequestedRef.current = true;
    const op = useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
    void previewGenerate(toGenerateParams(subject, pendingParams))
      .then(({ prompts }) => {
        op.end("completed");
        if (cancelled) return;
        if (isValidPromptPreviewResponse(prompts)) {
          setPromptPreviews(prompts);
        }
      })
      .catch(() => op.end("failed"));
    return () => { cancelled = true; op.end("superseded"); };
  }, [coreQuestionResolution, pendingParams, subject]);

  // Debounced re-fetch triggered by 確認頁修改 (#445).
  // Gates on hasPendingConfirmationEdits so that opening the confirmation screen
  // (which sets pendingPerQuestionParams) does not schedule a spurious second fetch.
  // #446: captures which 題組 indices were edited so failures can be scoped per-題組.
  useEffect(() => {
    if (
      restoredConfirmationEffectsSuppressedRef.current ||
      !pendingParams ||
      !pendingPerQuestionParams ||
      !hasPendingConfirmationEdits
    ) return;

    // Snapshot the edited indices accumulated since the last effect run, then
    // reset the accumulator so the next edit cycle starts fresh.
    const capturedEditedIndices = new Set(pendingEditedIndicesRef.current);
    pendingEditedIndicesRef.current = new Set();

    const seq = ++previewRefetchSeqRef.current;

    const timeoutId = window.setTimeout(() => {
      if (seq !== previewRefetchSeqRef.current) return; // superseded before timeout fired
      setPreviewRefetchLoading(true);
      const formParams: typeof pendingParams = {
        ...pendingParams,
        per_question_params: JSON.stringify(pendingPerQuestionParams),
      };
      const fetchParams = toGenerateParams(subject, formParams);
      const op = useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
      void previewGenerate(fetchParams)
        .then(({ prompts }) => {
          if (seq !== previewRefetchSeqRef.current) {
            op.end("superseded");
            return;
          }
          op.end("completed");
          if (isValidPromptPreviewResponse(prompts)) {
            setPromptPreviews(prompts);
          }
          setPreviewRefetchLoading(false);
          // #446: clear stale state on success
          setStalePreviewIndices(new Set());
        })
        .catch(() => {
          if (seq !== previewRefetchSeqRef.current) {
            op.end("superseded");
            return;
          }
          op.end("failed");
          setPreviewRefetchLoading(false);
          // #446: mark only the edited 題組 as stale
          setStalePreviewIndices((prev) => new Set([...prev, ...capturedEditedIndices]));
        });
    }, 500);

    return () => { window.clearTimeout(timeoutId); };
  }, [hasPendingConfirmationEdits, pendingPerQuestionParams, pendingParams, subject]);

  useEffect(() => {
    if (
      restoredConfirmationEffectsSuppressedRef.current ||
      !pendingParams ||
      coreQuestionResolution !== "loading"
    ) return;
    let cancelled = false;
    const pendingSubjectFilter = Array.isArray(pendingParams.subject_filter)
      ? pendingParams.subject_filter
      : pendingParams.subject_filter
        ? [pendingParams.subject_filter]
        : undefined;
    const op = useWorkspaceStore.getState().beginOperation("core_question_planning", "generate.confirmation");
    void planCoreQuestions({
      topic: pendingParams.topic ?? "",
      subject,
      subject_filter: pendingSubjectFilter,
      grade: pendingParams.grade,
    }).then(({ candidates }) => {
      const selected = selectPlannedCoreQuestion(candidates);
      op.end(selected ? "completed" : "failed");
      if (cancelled) return;
      if (!selected) {
        setCoreQuestionResolution("failed");
        return;
      }
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
      const currentParams = pendingParamsRef.current;
      const currentPerQuestionParams = pendingPerQuestionParamsRef.current ??
        parsePerQuestionParams(currentParams?.per_question_params);
      if (currentParams) {
        const nextPerQuestionParams = currentPerQuestionParams.map((item) => ({
          ...item,
          core_question: selected,
        }));
        const nextParams = {
          ...currentParams,
          core_question: selected,
          per_question_params: JSON.stringify(nextPerQuestionParams),
        };
        pendingParamsRef.current = nextParams;
        pendingPerQuestionParamsRef.current = nextPerQuestionParams;
      }
      setCoreQuestionResolution("generated");
    }).catch(() => {
      op.end("failed");
      if (cancelled) return;
      setCoreQuestionResolution("failed");
    });
    return () => { cancelled = true; op.end("aborted"); };
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
    // When recovering, keep the recovered field values — do not reset to
    // initialParams / schema defaults (issue #772). Schema is still fetched
    // for display and validation purposes.
    if (!recoveryForm) {
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
        textInstruction: stringFromInit("text_instruction", ""),
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
        learningPerformance: fromInit<string[]>("learning_performance", []),
        learningContent: fromInit<string[]>("learning_content", []),
        subQuestionCount: fromInit<number | "">("sub_question_count", ""),
        subquestionConfigs: subquestionConfigsFromInit(),
        contentDomain: stringFromInit("content_domain", ""),
        targetSurface: ip.target_surface === "數位" ? "數位" : "紙本",
        topic: fromInit<string>("topic", ""),
        coreQuestion: fromInit<string | null>("core_question", null),
        coreQuestionCallback: fromInit<boolean>("core_question_callback", true),
      }));
    }
    const initialGrade = typeof ip.grade === "number" ? ip.grade : undefined;
    const seq = ++curriculumRequestSeq.current;
    fetchCurriculumPool(subject, initialGrade)
      .then((s) => {
        if (cancelled) return;
        if (s.poolGrade === null && latestGradePoolSeq.current > seq) {
          // Keep the newer grade pool while applying grade-independent schema fields.
          setSchemas((prev) => prev ? {
            ...s,
            學習表現: prev.學習表現,
            學習內容: prev.學習內容,
            科目: prev.科目,
            poolGrade: prev.poolGrade,
          } : s);
        } else {
          setSchemas(s);
          if (s.poolGrade !== null) latestGradePoolSeq.current = seq;
        }
        if (!recoveryForm) {
          if (s.grades.length > 0 && ip.grade === undefined) setField("grade", s.grades[0]);
          if (
            subject === "natural_sciences" &&
            s.情境.length > 0 &&
            ip.context === undefined
          ) {
            if (ip.sub_context !== undefined) {
              const admittedContexts = s.情境子類別?.find(
                (entry) => entry.value === ip.sub_context,
              )?.admitted_by?.["情境"] ?? [];
              if (admittedContexts.length > 0) {
                setField("context", admittedContexts);
                userChosenFields.current.add("context");
              }
            } else {
              setField("context", [s.情境[0].value]);
              const firstSub = filterEntriesByAdmittedParent(
                s.情境子類別 ?? [],
                "情境",
                s.情境[0].value,
              )[0];
              setField("subContext", firstSub?.value ?? "");
            }
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
        }
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
        if (recoveryForm) {
          setModelsResolved(true);
          return;
        }
        // Reconcile any localStorage-hydrated selection against the live
        // allowlist — a stale value (e.g. a model that was removed server
        // side) must never be silently submitted.
        // Effort levels are also reconciled atomically: if the persisted
        // effort is not supported by the reconciled model, fall back to
        // defaults.effort_plan / defaults.effort_execute. An unset effort
        // also takes the advertised default once discovery resolves.
        const allowed = new Set(m.allowed);
        const reconcileEffortLevel = (
          effortValue: string,
          modelId: string,
          effortMap: Record<string, string[]> | undefined,
          defaultEffort: string,
        ): string => {
          if (!effortValue) return defaultEffort;
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
        if (recoveryForm && recoveryConfirmation) {
          // A recovered confirmation cannot be submitted without knowing
          // whether its model/effort values still belong to the current
          // registry. Keep the surface hydrating so the captured values stay
          // visible but remain explicitly blocked until discovery succeeds.
          return;
        }
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
  }, [recoveryConfirmation, recoveryForm, restoreFormSnapshot, setField]);

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

  // Re-fetch grade-dependent fields when grade changes so the correct learning stage is used.
  useEffect(() => {
    if (grade === "") return;
    let cancelled = false;
    const seq = ++curriculumRequestSeq.current;
    fetchCurriculumPool(subject, grade)
      .then((s) => {
        if (cancelled) return;
        setSchemas((prev) => prev ? { ...prev, 學習表現: s.學習表現, 學習內容: s.學習內容, 科目: s.科目, poolGrade: s.poolGrade } : s);
        latestGradePoolSeq.current = seq;
      })
      .catch(() => {/* non-critical — keep existing list */});
    return () => { cancelled = true; };
  }, [subject, grade]);

  const availableLearningPerformance = useMemo(() => {
    const entries = schemas?.學習表現 ?? [];
    if (subject === "natural_sciences") return entries;
    return filterCurriculumEntriesBySubject(
      entries,
      subject,
      subjectFilter,
      schemas?.科目?.map((entry) => entry.value) ?? [],
    );
  }, [schemas, subjectFilter, subject]);

  const availableSubContexts = useMemo(() => {
    const entries = schemas?.情境子類別 ?? [];
    const selectedContext = context[0] ?? "";
    return filterEntriesByAdmittedParent(entries, "情境", selectedContext);
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
    if (recoveryForm || invalidDigitalOnlyPins.length === 0) return;
    // A schema update or a surface flip can expose a stale history pin. Clear
    // it before submit so the backend never receives a known 422 combination.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setField("subquestionConfigs", (prev) => prev.map((config) =>
      config.question_type !== undefined && invalidDigitalOnlyPins.includes(config.question_type)
        ? { ...config, question_type: undefined }
        : config,
    ));
    setSurfaceQuestionTypeNotice(invalidDigitalOnlyPins);
  }, [invalidDigitalOnlyPins, recoveryForm, setField]);

  const availableLearningContent = useMemo(() => {
    const entries = schemas?.學習內容 ?? [];
    if (subject === "math" || subject === "social_studies") {
      return filterCurriculumEntriesBySubject(
        entries,
        subject,
        subjectFilter,
        schemas?.科目?.map((entry) => entry.value) ?? [],
      );
    }
    if (subject === "natural_sciences") {
      if (!subjectFilter) return entries;
      return entries.filter((e) => !e.科目 || e.科目 === subjectFilter);
    }
    return entries;
  }, [schemas, subjectFilter, subject]);

  useEffect(() => {
    if (!schemas || !initialParams || recoveryForm) return;
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
    const dropped: string[] = [];
    const poolMatchesGrade = schemas.poolGrade === (grade === "" ? null : grade);
    if (poolMatchesGrade) {
      const configs = parseSubquestionConfigs(ip.subquestion_configs);
      // Report the selections removed by the curriculum reconciliation effects below.
      for (const [label, values, entries] of [
        ["學習表現", [
          ...arr("learning_performance"),
          ...configs.flatMap((cfg) => cfg.learning_performance ?? []),
        ], availableLearningPerformance],
        ["學習內容", arr("learning_content"), availableLearningContent],
      ] as const) {
        const allowed = new Set(entries.map((entry) => entry.value));
        for (const code of new Set(values)) {
          if (!allowed.has(code)) dropped.push(`${label}: ${code}`);
        }
      }
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reconcile the notice with initialParams and the freshly-loaded schemas
    setPrefillNotice([
      normalisedHistoryPrefill.retiredItems.length > 0
        ? t("form.history_prefill_retired_notice").replace(
            "{items}",
            normalisedHistoryPrefill.retiredItems.join("、"),
          )
        : null,
      missing.length > 0 ? t("history.prefill_notice") : null,
      dropped.length > 0
        ? t("history.prefill_dropped_codes").replace("{items}", dropped.join("、"))
        : null,
    ].filter((message): message is string => message !== null).join(" ") || null);
    if (missing.length > 0) {
      // Drop the missing entries so the form submits a clean payload.
      const allowedCtx = new Set(schemas.情境?.map((s) => s.value));
      setField("context", (prev) => {
        const next = prev.filter((v) => allowedCtx.has(v));
        return next.length === prev.length ? prev : next;
      });
      const allowedQT = new Set(schemas.題型?.map((s) => s.value));
      setField("qType", (prev) => {
        const next = prev.filter((v) => allowedQT.has(v));
        return next.length === prev.length ? prev : next;
      });
      const allowedST = new Set(schemas.題型種類?.map((s) => s.value));
      setField("setType", (prev) => (allowedST.has(prev) ? prev : ""));
      const allowedDomains = new Set(schemas.內容領域?.map((s) => s.value));
      setField("contentDomain", (prev) => (prev && allowedDomains.has(prev) ? prev : ""));
    }
  }, [schemas, initialParams, ip, normalisedHistoryPrefill, t, setField, grade, availableLearningPerformance, availableLearningContent, recoveryForm]);

  const iccsDomainMappedCodes = useMemo(() => {
    if (
      subject !== "social_studies" ||
      !ICCS_DOMAIN_FILTER_SUBJECTS.has(subjectFilter) ||
      !contentDomain ||
      !schemas?.內容領域_mapping
    ) {
      return undefined;
    }
    return new Set(
      Object.entries(schemas.內容領域_mapping)
        .filter(([, domains]) => domains.includes(contentDomain))
        .map(([code]) => code),
    );
  }, [contentDomain, schemas, subject, subjectFilter]);

  const filteredLpPool = useMemo(() => {
    if (iccsDomainMappedCodes === undefined) return undefined;
    return availableLearningPerformance
      .filter((entry) => !isPublicSocialStudiesCode(entry.value) || iccsDomainMappedCodes.has(entry.value))
      .map((entry) => entry.value);
  }, [availableLearningPerformance, iccsDomainMappedCodes]);

  const filteredLcPool = useMemo(() => {
    if (
      subject !== "social_studies" ||
      !ICCS_DOMAIN_FILTER_SUBJECTS.has(subjectFilter) ||
      !contentDomain
    ) {
      return undefined;
    }
    return filterLearningContentEntriesByDomain(
      availableLearningContent,
      subject,
      subjectFilter,
      contentDomain,
      schemas?.內容領域_mapping,
    )
      .map((entry) => entry.value);
  }, [availableLearningContent, contentDomain, schemas, subject, subjectFilter]);

  const restrictCodesToIccsDomain = (codes: readonly string[]): string[] => {
    if (iccsDomainMappedCodes === undefined) return [...codes];
    return codes.filter(
      (code) => !isPublicSocialStudiesCode(code) || iccsDomainMappedCodes.has(code),
    );
  };

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
    if (recoveryForm || subject !== "natural_sciences" || !schemas || availableSubContexts.length === 0) return;
    const allowed = new Set(availableSubContexts.map((entry) => entry.value));
    if (!subContext || !allowed.has(subContext)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- fill the first valid dependent sub-context after schema load
      setField("subContext", availableSubContexts[0]?.value ?? "");
    }
  }, [availableSubContexts, recoveryForm, schemas, subContext, subject, setField]);

  useEffect(() => {
    if (recoveryForm || !schemas || schemas.poolGrade !== (grade === "" ? null : grade)) return;
    const allowed = new Set(availableLearningPerformance.map((entry) => entry.value));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reconcile history/draft curriculum selections with the loaded pool
    restoreFormSnapshot((current) => {
      // A draft restore can change the grade before this queued update runs.
      if (schemas.poolGrade !== (current.grade === "" ? null : current.grade)) return current;
      return {
        ...current,
        learningPerformance: current.learningPerformance.filter((value) => allowed.has(value)),
        subquestionConfigs: current.subquestionConfigs.map((cfg) =>
          cfg.learning_performance?.length
            ? { ...cfg, learning_performance: cfg.learning_performance.filter((v) => allowed.has(v)) }
            : cfg,
        ),
      };
    });
  }, [availableLearningPerformance, grade, recoveryForm, schemas, restoreFormSnapshot]);

  useEffect(() => {
    if (recoveryForm || !schemas || schemas.poolGrade !== (grade === "" ? null : grade)) return;
    const allowed = new Set(availableLearningContent.map((entry) => entry.value));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reconcile history/draft curriculum selections with the loaded pool
    restoreFormSnapshot((current) => {
      if (schemas.poolGrade !== (current.grade === "" ? null : current.grade)) return current;
      return {
        ...current,
        learningContent: current.learningContent.filter((value) => allowed.has(value)),
      };
    });
  }, [availableLearningContent, grade, recoveryForm, schemas, restoreFormSnapshot]);

  // Compute recovered invalid fields after schemas / models load (issues #772/#773).
  // Only relevant when an ordinary form was recovered; confirmation validity is
  // tracked independently below so the two workspaces remain distinct.
  useEffect(() => {
    if (!recoveryForm || !schemas) return;
    const invalid = new Set<string>();
    const hasInvalid = (values: readonly string[], entries: readonly SchemaEntry[] | undefined) =>
      values.some((value) => value !== "" && !(entries ?? []).some((entry) => entry.value === value));
    const allowedGrade = schemas.grades.includes(grade as number);
    if (grade !== "" && !allowedGrade) invalid.add("grade");
    if (hasInvalid(qType, schemas.題型)) invalid.add("qType");
    if (hasInvalid(context, schemas.情境)) invalid.add("context");
    if (setType && hasInvalid([setType], schemas.題型種類)) invalid.add("setType");
    if (contentType && hasInvalid([contentType], schemas.題目內容類型)) invalid.add("contentType");
    if (subjectFilter && hasInvalid([subjectFilter], schemas.科目)) invalid.add("subjectFilter");
    if (contentDomain && hasInvalid([contentDomain], schemas.內容領域)) invalid.add("contentDomain");
    if (style && hasInvalid([style], schemas.question_style)) invalid.add("style");
    if (difficulty && !["easy", "medium", "hard"].includes(difficulty)) invalid.add("difficulty");
    if (imageGenerationMode !== "html" && imageGenerationMode !== "gpt_image") {
      invalid.add("imageGenerationMode");
    }
    if (reportingScale && hasInvalid([reportingScale], schemas.reporting_scale)) {
      invalid.add("reportingScale");
    }
    if (subContext && hasInvalid([subContext], availableSubContexts)) invalid.add("subContext");
    if (hasInvalid(scienceCompetency, schemas.科學能力)) invalid.add("scienceCompetency");

    const gradePoolReady = schemas.poolGrade === null || schemas.poolGrade === grade;
    if (gradePoolReady) {
      if (hasInvalid(learningPerformance, availableLearningPerformance)) invalid.add("learningPerformance");
      if (hasInvalid(learningContent, availableLearningContent)) invalid.add("learningContent");
      const configs = subquestionConfigs;
      configs.forEach((config, index) => {
        if (config.question_type && hasInvalid([config.question_type], availableQuestionTypes)) {
          invalid.add(`subquestionConfigs[${index}].question_type`);
        }
        if (config.content_type && hasInvalid([config.content_type], schemas.題目內容類型)) {
          invalid.add(`subquestionConfigs[${index}].content_type`);
        }
        if (config.learning_content && hasInvalid(config.learning_content, availableLearningContent)) {
          invalid.add(`subquestionConfigs[${index}].learning_content`);
        }
        if (config.learning_performance && hasInvalid(config.learning_performance, availableLearningPerformance)) {
          invalid.add(`subquestionConfigs[${index}].learning_performance`);
        }
      });
    }

    if (subQuestionCount !== "" &&
      (!Number.isInteger(subQuestionCount) || subQuestionCount < 3 || subQuestionCount > 7)) {
      invalid.add("subQuestionCount");
    }
    if (textWordLimit !== null && textWordLimit !== undefined &&
      (!Number.isInteger(textWordLimit) || textWordLimit < 1)) {
      invalid.add("textWordLimit");
    }

    if (models?.effort) {
      const modelValues: Array<[keyof AvailableModels["defaults"], string]> = [
        ["plan", modelPlan],
        ["execute", modelExecute],
        ["verify", modelVerify],
        ["correct", modelCorrect],
      ];
      const allowedModels = new Set(models.allowed);
      for (const [, model] of modelValues) {
        if (model && !allowedModels.has(model)) invalid.add("models");
      }
      const effectiveModel = (tierModel: string, fallback: string) =>
        tierModel || fallback;
      const effortChecks: Array<[string, string, string]> = [
        ["effortPlan", effortPlan, effectiveModel(modelPlan, models.defaults.plan)],
        ["effortExecute", effortExecute, effectiveModel(modelExecute, models.defaults.execute)],
        [
          "effortVerify",
          effortVerify,
          effectiveModel(modelVerify, modelExecute || models.defaults.execute),
        ],
        [
          "effortCorrect",
          effortCorrect,
          effectiveModel(modelCorrect, modelExecute || models.defaults.execute),
        ],
      ];
      for (const [field, effort, model] of effortChecks) {
        if (effort && models.effort[model] && !models.effort[model].includes(effort)) {
          invalid.add(field);
        }
      }
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect -- stable setter; no loop risk (deps don't include the state it sets)
    setRecoveredInvalidFields(invalid);
  }, [
    availableLearningContent,
    availableLearningPerformance,
    availableQuestionTypes,
    availableSubContexts,
    contentDomain,
    contentType,
    context,
    difficulty,
    effortCorrect,
    effortExecute,
    effortPlan,
    effortVerify,
    grade,
    imageGenerationMode,
    learningContent,
    learningPerformance,
    models,
    modelCorrect,
    modelExecute,
    modelPlan,
    modelVerify,
    qType,
    recoveryForm,
    reportingScale,
    schemas,
    scienceCompetency,
    setType,
    style,
    subContext,
    subQuestionCount,
    subquestionConfigs,
    subjectFilter,
    textWordLimit,
  ]);

  const confirmationInvalidFields = useMemo(() => {
    const invalid = new Map<string, true>();
    if (!recoveryConfirmation || !pendingParams || !schemas) return invalid;

    const add = (path: string) => invalid.set(path, true);
    const valuesOf = (value: unknown): string[] => {
      if (Array.isArray(value)) {
        return value.filter((item): item is string => typeof item === "string" && item !== "");
      }
      return typeof value === "string" && value !== "" ? [value] : [];
    };
    const checkValues = (
      path: string,
      value: unknown,
      entries: readonly SchemaEntry[],
    ) => {
      if (
        value !== null && value !== undefined &&
        (Array.isArray(value)
          ? value.some((item) => typeof item !== "string")
          : typeof value !== "string")
      ) {
        add(path);
        return;
      }
      const allowed = new Set(entries.map((entry) => entry.value));
      if (valuesOf(value).some((item) => !allowed.has(item))) add(path);
    };
    const checkContentType = (
      path: string,
      value: unknown,
      entries: readonly SchemaEntry[],
    ) => {
      if (
        value !== null && value !== undefined &&
        (Array.isArray(value)
          ? value.some((item) => typeof item !== "string")
          : typeof value !== "string")
      ) {
        add(path);
        return;
      }
      const allowed = new Set(entries.map((entry) => entry.value));
      const customAllowed = allowed.has("customized");
      if (valuesOf(value).some((item) => !allowed.has(item) && !(customAllowed && item === "customized"))) {
        add(path);
      }
    };
    const checkNumbers = (path: string, value: unknown, minimum = 1) => {
      if (value !== undefined && value !== null &&
        (typeof value !== "number" || !Number.isInteger(value) || value < minimum)) {
        add(path);
      }
    };
    const checkBoolean = (path: string, value: unknown) => {
      if (value !== undefined && typeof value !== "boolean") add(path);
    };
    const admittedValues = (
      entries: readonly SchemaEntry[],
      parentKey: string,
      parentValue: unknown,
    ): SchemaEntry[] => {
      const parents = valuesOf(parentValue);
      if (parents.length === 0) return entries.filter((entry) => !entry.admitted_by?.[parentKey]);
      return entries.filter((entry) => {
        const admitted = entry.admitted_by?.[parentKey];
        if (Array.isArray(admitted)) return parents.some((parent) => admitted.includes(parent));
        return entry.parent === undefined || parents.includes(entry.parent);
      });
    };
    const params = pendingParams as unknown as Record<string, unknown>;
    const allSubjectValues = schemas.科目?.map((entry) => entry.value) ?? [];
    const subjectFor = (row: Record<string, unknown>) =>
      row.subject_filter ?? params.subject_filter;
    const domainFor = (row: Record<string, unknown>) =>
      typeof row.content_domain === "string"
        ? row.content_domain
        : typeof params.content_domain === "string"
          ? params.content_domain
          : undefined;
    const curriculumEntriesFor = (
      row: Record<string, unknown>,
      entries: SchemaEntry[],
    ) => filterLearningContentEntriesByDomain(
      filterCurriculumEntriesBySubject(
        entries,
        subject,
        subjectFor(row) as string | readonly string[] | undefined,
        allSubjectValues,
      ),
      subject,
      subjectFor(row) as string | readonly string[] | undefined,
      domainFor(row),
      schemas.內容領域_mapping,
    );

    const naturalQuestionTypes = [
      ...schemas.題型,
      ...["Simple multiple-choice", "Complex multiple-choice", "Constructed response"]
        .filter((value) => !schemas.題型.some((entry) => entry.value === value))
        .map((value) => ({ value, instruction: "" })),
    ];
    const questionTypes = subject === "natural_sciences"
      ? naturalQuestionTypes
      : schemas.題型;
    const reportingScales = schemas.reporting_scale ??
      ["1c", "1b", "1a", "2", "3", "4", "5", "6"].map((value) => ({ value, instruction: "" }));
    const imageModes = ["html", "gpt_image"].map((value) => ({ value, instruction: "" }));

    const checkEffort = (
      path: string,
      value: unknown,
      model: unknown,
      fallbackModel: unknown,
    ) => {
      if (!models?.effort || value === undefined || value === "") return;
      const modelId = typeof model === "string" && model !== ""
        ? model
        : typeof fallbackModel === "string" ? fallbackModel : "";
      const allowed = modelId && models.effort[modelId]
        ? models.effort[modelId]
        : [...new Set(Object.values(models.effort).flat())];
      // Some compatible model registries do not publish effort options. In
      // that case there is no current-schema value against which to validate
      // the restored setting; preserve it until the server can validate the
      // submitted payload.
      if (allowed.length === 0) return;
      if (!allowed.includes(value as string)) add(path);
    };
    const checkModel = (path: string, value: unknown) => {
      if (!models || value === undefined || value === null || value === "") return;
      if (typeof value !== "string" || !models.allowed.includes(value)) add(path);
    };

    const validateConfigRows = (
      rowPrefix: string,
      row: Record<string, unknown>,
      rowLearningContent: SchemaEntry[],
      rowLearningPerformance: SchemaEntry[],
    ) => {
      const configs = parseSubquestionConfigs(row.subquestion_configs);
      configs.forEach((config, subquestionIndex) => {
        const configRecord = config as Record<string, unknown>;
        const prefix = `${rowPrefix}subquestion_configs[${subquestionIndex}].`;
        checkValues(`${prefix}question_type`, configRecord.question_type, questionTypes);
        checkContentType(`${prefix}content_type`, configRecord.content_type, schemas.題目內容類型 ?? []);
        checkValues(`${prefix}cognitive_process`, configRecord.cognitive_process, schemas.認知歷程 ?? []);
        checkValues(`${prefix}reporting_scale`, configRecord.reporting_scale, reportingScales);
        checkValues(`${prefix}learning_content`, configRecord.learning_content, rowLearningContent);
        checkValues(`${prefix}learning_performance`, configRecord.learning_performance, rowLearningPerformance);
        if (subject === "social_studies" || subject === "natural_sciences") {
          const figureKind = configRecord.figure_kind;
          const figureKinds = schemas.figure_kinds;
          if (
            typeof figureKind === "string" &&
            figureKind !== "" &&
            figureKinds !== undefined &&
            figureKinds.length > 0 &&
            !figureKinds.includes(figureKind)
          ) {
            add(`${prefix}figure_kind`);
          }
        }
        if (configRecord.image_generation_mode !== undefined &&
          configRecord.image_generation_mode !== "" &&
          configRecord.image_generation_mode !== "html" &&
          configRecord.image_generation_mode !== "gpt_image") {
          add(`${prefix}image_generation_mode`);
        }
        checkNumbers(`${prefix}question_word_limit`, configRecord.question_word_limit);
        checkNumbers(`${prefix}option_word_limit`, configRecord.option_word_limit);
      });
    };

    const topRow = params;
    if (
      topRow.grade !== undefined &&
      (typeof topRow.grade !== "number" || !schemas.grades.includes(topRow.grade))
    ) {
      add("confirmation.grade");
    }
    checkValues("confirmation.context", topRow.context, schemas.情境);
    checkValues("confirmation.set_type", topRow.set_type, schemas.題型種類);
    checkValues("confirmation.q_type", topRow.q_type, questionTypes);
    checkContentType("confirmation.content_type", topRow.content_type, schemas.題目內容類型 ?? []);
    checkValues("confirmation.subject_filter", topRow.subject_filter, schemas.科目 ?? []);
    checkValues(
      "confirmation.sub_context",
      topRow.sub_context,
      admittedValues(schemas.情境子類別 ?? [], "情境", topRow.context),
    );
    checkValues("confirmation.science_competency", topRow.science_competency, schemas.科學能力 ?? []);
    checkValues("confirmation.content_domain", topRow.content_domain, schemas.內容領域 ?? []);
    checkValues("confirmation.reporting_scale", topRow.reporting_scale, reportingScales);
    checkValues("confirmation.core_competency", topRow.core_competency, schemas.核心素養 ?? []);
    checkValues("confirmation.math_thinking", topRow.math_thinking, schemas.數學思考);
    checkValues("confirmation.style", topRow.style, schemas.question_style ?? []);
    const topLearningContent = curriculumEntriesFor(topRow, schemas.學習內容 ?? []);
    const topLearningPerformance = curriculumEntriesFor(topRow, schemas.學習表現 ?? []);
    checkValues("confirmation.learning_content", topRow.learning_content, topLearningContent);
    checkValues("confirmation.learning_performance", topRow.learning_performance, topLearningPerformance);
    validateConfigRows("confirmation.", topRow, topLearningContent, topLearningPerformance);
    checkValues("confirmation.image_generation_mode", topRow.image_generation_mode, imageModes);
    checkNumbers("confirmation.count", topRow.count);
    if (topRow.sub_question_count !== undefined && topRow.sub_question_count !== null &&
      (typeof topRow.sub_question_count !== "number" ||
        !Number.isInteger(topRow.sub_question_count) ||
        topRow.sub_question_count < 3 || topRow.sub_question_count > 7)) {
      add("confirmation.sub_question_count");
    }
    checkNumbers("confirmation.text_word_limit", topRow.text_word_limit);
    checkBoolean("confirmation.skip_verify", topRow.skip_verify);
    checkBoolean("confirmation.disable_reference_fewshot", topRow.disable_reference_fewshot);
    checkBoolean("confirmation.core_question_callback", topRow.core_question_callback);
    checkBoolean("confirmation.allow_duplicate_figure_kinds", topRow.allow_duplicate_figure_kinds);
    if (subject === "social_studies" && topRow.target_surface !== undefined &&
      topRow.target_surface !== "紙本" && topRow.target_surface !== "數位") {
      add("confirmation.target_surface");
    }
    if (typeof topRow.difficulty === "string" && topRow.difficulty !== "" &&
      !["easy", "medium", "hard"].includes(topRow.difficulty)) {
      add("confirmation.difficulty");
    }

    if (models) {
      for (const key of ["model_plan", "model_execute", "model_verify", "model_correct"]) {
        checkModel(`confirmation.${key}`, topRow[key]);
      }
      checkEffort("confirmation.effort_plan", topRow.effort_plan, topRow.model_plan, models.defaults.plan);
      checkEffort("confirmation.effort_execute", topRow.effort_execute, topRow.model_execute, models.defaults.execute);
      const executeModel = typeof topRow.model_execute === "string" && topRow.model_execute !== ""
        ? topRow.model_execute
        : models.defaults.execute;
      checkEffort("confirmation.effort_verify", topRow.effort_verify, topRow.model_verify, executeModel);
      checkEffort("confirmation.effort_correct", topRow.effort_correct, topRow.model_correct, executeModel);
    }

    const rows = pendingPerQuestionParams ?? parsePerQuestionParams(params.per_question_params);
    rows.forEach((row, index) => {
      const rowPrefix = `per_question_params[${index}].`;
      const rowRecord = row as Record<string, unknown>;
      if (
        rowRecord.grade !== undefined && rowRecord.grade !== null &&
        (typeof rowRecord.grade !== "number" || !Number.isInteger(rowRecord.grade) ||
          !schemas.grades.includes(rowRecord.grade))
      ) {
        add(`${rowPrefix}grade`);
      }
      for (const key of ["model_plan", "model_execute", "model_verify", "model_correct"]) {
        checkModel(`${rowPrefix}${key}`, rowRecord[key]);
      }
      checkValues(`${rowPrefix}style`, rowRecord.style, schemas.question_style ?? []);
      checkContentType(`${rowPrefix}content_type`, rowRecord.content_type, schemas.題目內容類型 ?? []);
      checkValues(`${rowPrefix}context`, rowRecord.context, schemas.情境);
      checkValues(`${rowPrefix}set_type`, rowRecord.set_type, schemas.題型種類);
      checkValues(`${rowPrefix}q_type`, rowRecord.q_type, questionTypes);
      checkValues(`${rowPrefix}subject_filter`, rowRecord.subject_filter, schemas.科目 ?? []);
      checkValues(
        `${rowPrefix}sub_context`,
        rowRecord.sub_context,
        admittedValues(schemas.情境子類別 ?? [], "情境", rowRecord.context ?? topRow.context),
      );
      checkValues(`${rowPrefix}science_competency`, rowRecord.science_competency, schemas.科學能力 ?? []);
      checkValues(`${rowPrefix}內容領域`, rowRecord.content_domain, schemas.內容領域 ?? []);
      checkValues(`${rowPrefix}核心素養`, rowRecord.core_competency, schemas.核心素養 ?? []);
      checkValues(`${rowPrefix}數學思考`, rowRecord.math_thinking, schemas.數學思考);
      checkValues(`${rowPrefix}認知歷程`, rowRecord.cognitive_process, schemas.認知歷程 ?? []);
      checkValues(`${rowPrefix}reporting_scale`, rowRecord.reporting_scale, reportingScales);
      if (rowRecord.sub_question_count !== undefined && rowRecord.sub_question_count !== null &&
        (typeof rowRecord.sub_question_count !== "number" ||
          !Number.isInteger(rowRecord.sub_question_count) || rowRecord.sub_question_count < 3 || rowRecord.sub_question_count > 7)) {
        add(`${rowPrefix}sub_question_count`);
      }
      checkEffort(`${rowPrefix}effort_plan`, rowRecord.effort_plan, rowRecord.model_plan, topRow.model_plan ?? models?.defaults.plan);
      checkEffort(`${rowPrefix}effort_execute`, rowRecord.effort_execute, rowRecord.model_execute, topRow.model_execute ?? models?.defaults.execute);
      const rowExecuteModel = rowRecord.model_execute ?? topRow.model_execute ?? models?.defaults.execute;
      checkEffort(`${rowPrefix}effort_verify`, rowRecord.effort_verify, rowRecord.model_verify, rowExecuteModel);
      checkEffort(`${rowPrefix}effort_correct`, rowRecord.effort_correct, rowRecord.model_correct, rowExecuteModel);
      const rowLearningContent = curriculumEntriesFor(rowRecord, schemas.學習內容 ?? []);
      const rowLearningPerformance = curriculumEntriesFor(rowRecord, schemas.學習表現 ?? []);
      checkValues(`${rowPrefix}learning_content`, rowRecord.learning_content, rowLearningContent);
      checkValues(`${rowPrefix}learning_performance`, rowRecord.learning_performance, rowLearningPerformance);
      validateConfigRows(rowPrefix, rowRecord, rowLearningContent, rowLearningPerformance);
      checkValues(`${rowPrefix}image_generation_mode`, rowRecord.image_generation_mode, imageModes);
    });

    return invalid;
  }, [models, pendingParams, pendingPerQuestionParams, recoveryConfirmation, schemas, subject]);
  const confirmationHasInvalidFields =
    confirmInvalidFields.size > 0 || confirmationInvalidFields.size > 0;
  const confirmationHydrating = recoveryConfirmation !== undefined && formReadiness !== "ready";

  // Sync per-subquestion config rows with the selected count.
  useEffect(() => {
    if (recoveryForm) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- keep the editor row count synchronized with the selected count
    setField("subquestionConfigs", (prev) => rebuildSubquestionSlots(prev, subQuestionCount));
  }, [recoveryForm, subQuestionCount, setField]);

  function updateSubquestionConfig(index: number, patch: Partial<SubQuestionConfig>) {
    const editedFields = editedSubquestionFieldsRef.current.get(index) ?? new Set();
    for (const field of Object.keys(patch) as Array<keyof SubQuestionConfig>) {
      editedFields.add(field);
    }
    editedSubquestionFieldsRef.current.set(index, editedFields);
    setField("subquestionConfigs", (prev) => prev.map((cfg, i) =>
      i === index ? serialisableSubquestionConfig({ ...cfg, ...patch }) : cfg,
    ));
  }

  function toggleMulti(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function storeResolvedResponse(
    response: Awaited<ReturnType<typeof resolveGenerate>>,
    preserveConfirmationEdits: boolean,
  ) {
    const rawPerQuestionParams = response.payload.per_question_params;
    const perQuestionParams = rawPerQuestionParams === undefined
      ? null
      : normaliseResolvedPerQuestionParams(parsePerQuestionParams(rawPerQuestionParams));
    const resolvedParams = {
      ...response.payload,
      ...(perQuestionParams === null
        ? {}
        : { per_question_params: JSON.stringify(perQuestionParams) }),
      drawn: response.drawn,
    } as FormParams;
    setPendingParams(resolvedParams);
    pendingParamsRef.current = resolvedParams;
    setPendingPerQuestionParams(perQuestionParams);
    pendingPerQuestionParamsRef.current = perQuestionParams;
    setClearedPaths(response.cleared ?? []);
    setResolverLoading(false);
    setResolverError(null);
    setHasPendingConfirmationEdits(preserveConfirmationEdits);
    setStalePreviewIndices(new Set());
    pendingEditedIndicesRef.current = new Set();
    previewRequestedRef.current = false;
    restoredConfirmationEffectsSuppressedRef.current = false;
    setPromptPreviews([]);
  }

  async function resolveForConfirmation(
    payload: Record<string, unknown>,
    redraws: Record<string, number>,
    preserveConfirmationEdits: boolean,
    rebuildSubquestionSlots = false,
  ) {
    const sequence = ++resolveRequestSeqRef.current;
    resolveOperationRef.current?.end("superseded");
    const op = useWorkspaceStore.getState().beginOperation("resolve", "generate.confirmation");
    resolveOperationRef.current = op;
    resolveRequestRef.current = { payload, redraws, rebuildSubquestionSlots };
    setResolverLoading(true);
    setResolverError(null);
    try {
      const response = await resolveGenerate(payload, redraws);
      if (sequence !== resolveRequestSeqRef.current) return;
      const carriedDrawn = Array.isArray(payload.drawn)
        ? payload.drawn.filter((path): path is string => typeof path === "string")
        : [];
      storeResolvedResponse(
        {
          ...response,
          drawn: [...new Set([
            ...(rebuildSubquestionSlots
              ? filterDrawnAfterSubquestionCountRedraw(carriedDrawn, redraws)
              : carriedDrawn),
            ...response.drawn,
          ])],
        },
        preserveConfirmationEdits,
      );
      op.end("completed");
      if (resolveOperationRef.current === op) resolveOperationRef.current = null;
    } catch (cause) {
      if (sequence !== resolveRequestSeqRef.current) return;
      op.end("failed");
      if (resolveOperationRef.current === op) resolveOperationRef.current = null;
      setResolverLoading(false);
      setResolverError(
        cause instanceof Error && cause.message
          ? cause.message
          : t("form.confirm_resolve_error"),
      );
    }
  }

  function retryResolver() {
    const request = resolveRequestRef.current;
    if (!request || resolverLoading) return;
    void resolveForConfirmation(
      request.payload,
      request.redraws,
      pendingParamsRef.current !== null,
      request.rebuildSubquestionSlots,
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    restoredConfirmationEffectsSuppressedRef.current = false;
    previewRequestedRef.current = false;
    setPromptPreviews([]);
    setPendingParams(null);
    pendingParamsRef.current = null;
    setPendingPerQuestionParams(null);
    pendingPerQuestionParamsRef.current = null;
    setClearedPaths([]);
    setResolverError(null);
    if (grade === "") return;
    if (!setType.trim()) {
      setValidationError(t("form.error_set_type_required"));
      return;
    }
    setValidationError(null);
    const cleanPassage = passage === TEXT_HINT ? undefined : passage;
    const cleanOptions = options.filter((o) => o && o !== OPTION_HINT);
    const cleanTopic = topic.trim();
    const effectiveContentType = isCurriculumSubject
      ? (contentType === "customized" ? customContentType.trim() : contentType)
      : undefined;
    if (isCurriculumSubject && !effectiveContentType) return;
    const selectedLearningPerformance = restrictCodesToIccsDomain(learningPerformance);
    const lcPoolValues = filteredLcPool ?? availableLearningContent.map((entry) => entry.value);
    const selectedLearningContent = filteredLcPool === undefined
      ? restrictCodesToIccsDomain(learningContent)
      : learningContent.filter((code) => lcPoolValues.includes(code));
    const historyDrawn = Array.isArray(ip.drawn)
      ? ip.drawn.filter((path): path is string => typeof path === "string")
      : undefined;
    const hasHistoryPerQuestionParams = historyPerQuestionParams.length === count;
    const shouldSendSubquestionConfigs =
      (subject === "social_studies" || subject === "natural_sciences") && subQuestionCount !== "" && (
        subquestionConfigs.length > 0 || subQuestionCount > 0
      );

    const hasHistoryCoreQuestion = hasHistoryPerQuestionParams &&
      historyPerQuestionParams.some(
        (params) => typeof params.core_question === "string" && params.core_question.length > 0,
      );
    setCoreQuestionResolution(coreQuestion || hasHistoryCoreQuestion ? "idle" : "loading");
    const baseParams = {
      grade,
      style: subject === "math" && style ? style : undefined,
      content_type: effectiveContentType,
      context: subject === "natural_sciences" ? context.slice(0, 1) : context,
      set_type: setType,
      q_type: subject === "social_studies" ? [] : qType,
      count,
      coverage_mode: subject === "social_studies" ? coverageMode : undefined,
      skip_verify: skipVerify,
      disable_reference_fewshot: disableReferenceFewshot,
      image_generation_mode: imageGenerationMode,
      difficulty: subject !== "natural_sciences" && difficulty !== "" ? difficulty : undefined,
      reporting_scale: subject === "natural_sciences" && reportingScale !== "" ? reportingScale : undefined,
      ...(subject === "social_studies" || subject === "natural_sciences"
        ? { core_question_callback: coreQuestionCallback }
        : {}),
      subject_filter: subjectFilter || undefined,
      core_competency:
        subject === "math" || subject === "social_studies"
          ? fromInit<string[] | undefined>("core_competency", undefined)
          : undefined,
      math_thinking:
        subject === "math"
          ? fromInit<string[] | undefined>("math_thinking", undefined)
          : undefined,
      passage: cleanPassage,
      text_word_limit: canUseTextWordLimit ? (textWordLimit ?? undefined) : undefined,
      options: subject === "math" && cleanOptions.length ? cleanOptions : undefined,
      topic: isCurriculumSubject && cleanTopic ? cleanTopic : undefined,
      core_question: coreQuestion || undefined,
      text_instruction:
        (subject === "social_studies" || subject === "natural_sciences") && textInstruction.trim()
          ? textInstruction.trim()
          : undefined,
      ...(subject === "social_studies" && contentDomain
        ? { content_domain: contentDomain }
        : {}),
      ...(subject === "social_studies" && targetSurface === "數位"
        ? { target_surface: "數位" as const }
        : {}),
      learning_performance: isCurriculumSubject && selectedLearningPerformance.length > 0
        ? selectedLearningPerformance
        : undefined,
      sub_context: subject === "natural_sciences" ? subContext || undefined : undefined,
      science_competency: subject === "natural_sciences" && scienceCompetency.length > 0
        ? scienceCompetency
        : undefined,
      learning_content: isCurriculumSubject && selectedLearningContent.length > 0
        ? selectedLearningContent
        : undefined,
      sub_question_count: subQuestionCount !== "" ? subQuestionCount : undefined,
      subquestion_configs: shouldSendSubquestionConfigs
        ? JSON.stringify(subquestionConfigs.slice(0, subQuestionCount as number).map(serialisableSubquestionConfig))
        : undefined,
      model_plan: modelPlan || undefined,
      model_execute: modelExecute || undefined,
      model_verify: modelVerify || undefined,
      model_correct: modelCorrect || undefined,
      effort_plan: models?.effort ? effortPlan : undefined,
      effort_execute: models?.effort ? effortExecute : undefined,
      effort_verify: models?.effort ? (effortVerify || undefined) : undefined,
      effort_correct: models?.effort ? (effortCorrect || undefined) : undefined,
      // Omit when false so existing requests are byte-identical (issue #450).
      ...((subject === "social_studies" || subject === "natural_sciences") && allowDuplicateFigureKinds
        ? { allow_duplicate_figure_kinds: true as const }
        : {}),
      drawn: historyDrawn,
      ...(configuredSeed !== undefined ? { seed: configuredSeed } : {}),
    } as FormParams & { seed?: number };

    // text_instruction is now PER_QUESTION_FIELDS (#637): it is allowed in
    // per_question_params rows so must not be stripped here.
    const requestLevelFields = new Set([
      "subject",
      "count",
      "per_question_params",
      "drawn",
      "max_retries",
      "core_question_callback",
      "allow_duplicate_figure_kinds",
    ]);
    const perQuestionParams = hasHistoryPerQuestionParams
      ? historyPerQuestionParams.map((params) => {
          const questionParams = Object.fromEntries(
            Object.entries(params).filter(([key]) => !requestLevelFields.has(key)),
          );
          if (!shouldSendSubquestionConfigs) return questionParams;
          return {
            ...questionParams,
            subquestion_configs: mergeLiveSubquestionConfigs(
              params.subquestion_configs,
              subquestionConfigs.slice(0, subQuestionCount as number).map(serialisableSubquestionConfig),
              editedSubquestionFieldsRef.current,
              historyDraftChoice === "draft" || historyDraftChoice === "defaults",
            ),
          };
        })
      : Array.from({ length: count }, () => ({}));
    const partialParams = {
      ...baseParams,
      per_question_params: JSON.stringify(perQuestionParams),
    } as FormParams;
    setHasPendingConfirmationEdits(false);
    redrawsRef.current = {};
    void resolveForConfirmation(
      toGenerateParams(subject, partialParams) as unknown as Record<string, unknown>,
      {},
      false,
    );
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
    // Explicit submission acknowledges a restored snapshot without touching
    // the already-captured confirmation payload or ordinary form fields.
    if (showRecoveryBanner) acknowledgeRecoveryBanner();
    resolveRequestSeqRef.current += 1;
    resolveOperationRef.current?.end("superseded");
    resolveOperationRef.current = null;
    resolveRequestRef.current = null;
    pendingParamsRef.current = null;
    pendingPerQuestionParamsRef.current = null;
    setPendingParams(null);
    setPendingPerQuestionParams(null);
    setClearedPaths([]);
    setHasPendingConfirmationEdits(false);
    // #446: clear stale state on submit
    setStalePreviewIndices(new Set());
    onSubmit(submittedParams);
  }

  function updatePendingConfirmationField(
    questionIndex: number,
    field: string,
    value: unknown,
    redraw = false,
  ) {
    restoredConfirmationEffectsSuppressedRef.current = false;
    const currentParams = pendingParamsRef.current ?? pendingParams;
    const currentPerQuestionParams = pendingPerQuestionParamsRef.current ??
      parsePerQuestionParams(currentParams?.per_question_params);
    const questionParams = currentPerQuestionParams[questionIndex];
    if (!currentParams || !questionParams) return;

    const canonical = RESOLVER_FIELD_ALIASES[field] ?? field;
    const path = `per_question_params[${questionIndex}].${canonical}`;
    const parentChildren = CONFIRMATION_PARENT_CHILDREN[canonical];
    const aliases = new Set([
      path,
      `per_question_params[${questionIndex}].${field}`,
      ...(questionIndex === 0 ? [canonical, field] : []),
    ]);
    const nextPerQuestionParams = currentPerQuestionParams.map((params, index) => {
      if (index !== questionIndex) return params;
      const next = { ...params };
      if (value === undefined) {
        if (canonical === "sub_question_count") delete next[field];
        else next[field] = null;
      }
      else next[field] = value;
      if (parentChildren) {
        for (const drawnPath of currentParams.drawn ?? []) {
          if (isConfirmationChildPath(drawnPath, questionIndex, parentChildren)) {
            clearConfirmationPath(next, drawnPath, questionIndex);
          }
        }
      }
      return next;
    });
    const nextDrawn = (Array.isArray(currentParams.drawn) ? currentParams.drawn : [])
      .filter((drawnPath) => !aliases.has(drawnPath))
      .filter((drawnPath) => canonical === "sub_question_count" || !parentChildren || !isConfirmationChildPath(
        drawnPath,
        questionIndex,
        parentChildren,
      ));
    const nextParams = {
      ...currentParams,
      drawn: nextDrawn,
      per_question_params: JSON.stringify(nextPerQuestionParams),
    } as FormParams;
    if (value === undefined && canonical === "sub_question_count") {
      delete nextParams.sub_question_count;
    }
    const nextRedraws = (redraw || parentChildren)
      ? {
          ...redrawsRef.current,
          [path]: (redrawsRef.current[path] ?? 0) + 1,
        }
      : { ...redrawsRef.current };

    pendingParamsRef.current = nextParams;
    pendingPerQuestionParamsRef.current = nextPerQuestionParams;
    pendingEditedIndicesRef.current.add(questionIndex);
    redrawsRef.current = nextRedraws;
    setHasPendingConfirmationEdits(true);
    setPendingParams(nextParams);
    setPendingPerQuestionParams(nextPerQuestionParams);
    void resolveForConfirmation(
      toGenerateParams(subject, nextParams) as unknown as Record<string, unknown>,
      nextRedraws,
      true,
      canonical === "sub_question_count",
    );
  }

  function updatePendingSubquestionConfig(
    questionIndex: number,
    subquestionIndex: number,
    patch: Partial<SubQuestionConfig>,
  ) {
    restoredConfirmationEffectsSuppressedRef.current = false;
    const currentParams = pendingParamsRef.current ?? pendingParams;
    const currentPerQuestionParams = pendingPerQuestionParamsRef.current ??
      parsePerQuestionParams(currentParams?.per_question_params);
    const questionParams = currentPerQuestionParams[questionIndex];
    if (!currentParams || !questionParams) return;
    const configs = parseSubquestionConfigs(questionParams.subquestion_configs);
    if (!configs[subquestionIndex]) return;
    const nextConfigs = configs.map((config, index) => {
      if (index !== subquestionIndex) return config;
      const nextConfig = { ...config, ...patch } as Record<string, unknown>;
      if (Object.hasOwn(patch, "cognitive_process")) delete nextConfig["認知歷程"];
      return serialisableSubquestionConfig(nextConfig as SubQuestionConfig);
    });
    const nextPerQuestionParams = currentPerQuestionParams.map((params, index) =>
      index === questionIndex
        ? { ...params, subquestion_configs: JSON.stringify(nextConfigs) }
        : params,
    );
    const changedPaths = Object.keys(patch).flatMap((field) => {
      const path = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].`;
      return [
        `${path}${field}`,
        ...(field === "cognitive_process" ? [`${path}認知歷程`] : []),
      ];
    });
    const nextDrawn = (Array.isArray(currentParams.drawn) ? currentParams.drawn : [])
      .filter((path) => !changedPaths.includes(path));
    const nextParams = {
      ...currentParams,
      drawn: nextDrawn,
      per_question_params: JSON.stringify(nextPerQuestionParams),
    } as FormParams;
    pendingParamsRef.current = nextParams;
    pendingPerQuestionParamsRef.current = nextPerQuestionParams;
    pendingEditedIndicesRef.current.add(questionIndex);
    setHasPendingConfirmationEdits(true);
    setPendingParams(nextParams);
    setPendingPerQuestionParams(nextPerQuestionParams);
  }

  function updatePendingSubquestionInstruction(
    questionIndex: number,
    subquestionIndex: number,
    instruction: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      instruction: instruction.trim() || undefined,
    });
  }

  function updatePendingSubquestionQuestionType(
    questionIndex: number,
    subquestionIndex: number,
    questionType: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      question_type: questionType || undefined,
    });
  }

  function updatePendingSubquestionContentType(
    questionIndex: number,
    subquestionIndex: number,
    contentType: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      content_type: contentType || undefined,
    });
  }

  function updatePendingSubquestionImageMode(
    questionIndex: number,
    subquestionIndex: number,
    imageMode: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      image_generation_mode: imageMode === "html" || imageMode === "gpt_image"
        ? imageMode
        : undefined,
    });
  }

  function updatePendingSubquestionReportingScale(
    questionIndex: number,
    subquestionIndex: number,
    reportingScale: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      reporting_scale: reportingScale || undefined,
    });
  }

  function updatePendingSubquestionCognitiveProcess(
    questionIndex: number,
    subquestionIndex: number,
    cognitiveProcess: string,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      cognitive_process: cognitiveProcess || undefined,
    });
  }

  function updatePendingSubquestionQuestionWordLimit(
    questionIndex: number,
    subquestionIndex: number,
    value: number | undefined,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      question_word_limit: value,
    });
  }

  function updatePendingSubquestionOptionWordLimit(
    questionIndex: number,
    subquestionIndex: number,
    value: number | undefined,
  ) {
    updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
      option_word_limit: value,
    });
  }

  /**
   * Per-題組 文本出題指示 確認頁修改 (#637).
   *
   * A non-blank value pins a per-row override for that 題組 only and triggers the
   * debounced preview re-fetch.  A blank or whitespace-only value removes the
   * per-row override so the worker falls back to the request-level text_instruction.
   * Sibling 題組 rows and the form's own text_instruction value are never touched.
   */
  function updatePendingQuestionTextInstruction(
    questionIndex: number,
    value: string,
  ) {
    restoredConfirmationEffectsSuppressedRef.current = false;
    const currentParams = pendingParamsRef.current ?? pendingParams;
    const currentPerQuestionParams = pendingPerQuestionParamsRef.current ??
      parsePerQuestionParams(currentParams?.per_question_params);
    const questionParams = currentPerQuestionParams[questionIndex];
    if (!currentParams || !questionParams) return;
    const trimmed = value.trim();
    const nextPerQuestionParams = currentPerQuestionParams.map((params, i) => {
      if (i !== questionIndex) return params;
      const next = { ...params };
      if (trimmed) {
        next.text_instruction = trimmed;
      } else {
        delete next.text_instruction;
      }
      return next;
    });
    const nextParams = {
      ...currentParams,
      per_question_params: JSON.stringify(nextPerQuestionParams),
    } as FormParams;
    pendingParamsRef.current = nextParams;
    pendingPerQuestionParamsRef.current = nextPerQuestionParams;
    pendingEditedIndicesRef.current.add(questionIndex);
    setHasPendingConfirmationEdits(true);
    setPendingParams(nextParams);
    setPendingPerQuestionParams(nextPerQuestionParams);
  }

  /**
   * Generic gate: registers/clears a field's validity.
   * Any registered invalid field disables 確認送出.
   * This is field-agnostic — future editable fields call this the same way.
   */
  function setConfirmFieldValidity(
    questionIndex: number,
    subquestionIndex: number,
    fieldKey: string,
    isValid: boolean,
  ) {
    const key = `${questionIndex}-${subquestionIndex}-${fieldKey}`;
    setConfirmInvalidFields((prev) => {
      const next = new Map(prev);
      if (!isValid) {
        next.set(key, true);
      } else {
        next.delete(key);
      }
      return next;
    });
  }

  function resubmitSubquestionField(
    questionIndex: number,
    subquestionIndex: number,
    field: string,
  ) {
    restoredConfirmationEffectsSuppressedRef.current = false;
    const currentParams = pendingParamsRef.current ?? pendingParams;
    const currentPerQuestionParams = pendingPerQuestionParamsRef.current ??
      parsePerQuestionParams(currentParams?.per_question_params);
    const questionParams = currentPerQuestionParams[questionIndex];
    if (!currentParams || !questionParams) return;
    const configs = parseSubquestionConfigs(questionParams.subquestion_configs);
    if (!configs[subquestionIndex]) return;

    const nextConfigs = configs.map((config, index) => {
      if (index !== subquestionIndex) return config;
      const nextConfig = { ...config } as Record<string, unknown>;
      delete nextConfig[field];
      if (field === "cognitive_process" || field === "認知歷程") {
        delete nextConfig.cognitive_process;
        delete nextConfig["認知歷程"];
      }
      return serialisableSubquestionConfig(nextConfig);
    });
    const nextPerQuestionParams = currentPerQuestionParams.map((params, index) =>
      index === questionIndex
        ? { ...params, subquestion_configs: JSON.stringify(nextConfigs) }
        : params,
    );
    const canonicalField = field === "cognitive_process" ? "認知歷程" : field;
    const path =
      `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].${canonicalField}`;
    const nextDrawn = (Array.isArray(currentParams.drawn) ? currentParams.drawn : [])
      .filter((drawnPath) => drawnPath !== path && drawnPath !==
        `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].${field}`);
    const nextParams = {
      ...currentParams,
      drawn: nextDrawn,
      per_question_params: JSON.stringify(nextPerQuestionParams),
    } as FormParams;
    const nextRedraws = {
      ...redrawsRef.current,
      [path]: (redrawsRef.current[path] ?? 0) + 1,
    };
    pendingParamsRef.current = nextParams;
    pendingPerQuestionParamsRef.current = nextPerQuestionParams;
    pendingEditedIndicesRef.current.add(questionIndex);
    redrawsRef.current = nextRedraws;
    setHasPendingConfirmationEdits(true);
    setPendingParams(nextParams);
    setPendingPerQuestionParams(nextPerQuestionParams);
    void resolveForConfirmation(
      toGenerateParams(subject, nextParams) as unknown as Record<string, unknown>,
      nextRedraws,
      true,
    );
  }

  function resubmitSubquestionResolution(
    questionIndex: number,
    subquestionIndex: number,
    field: "learning_content" | "learning_performance",
  ) {
    resubmitSubquestionField(questionIndex, subquestionIndex, field);
  }

  function updatePendingSubquestionLc(
    questionIndex: number,
    subquestionIndex: number,
    lc: string[],
  ) {
    if (lc.length > 0) {
      updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
        learning_content: lc,
      });
      return;
    }
    resubmitSubquestionResolution(questionIndex, subquestionIndex, "learning_content");
  }

  // #446: retry handler — re-fetches using the CURRENT live configuration, not
  // a stale snapshot.  Building params here the same way the debounced effect
  // does means the race is harmless: whichever request lands last carries live
  // config either way.  On success the stale badge clears; on failure it stays
  // so the user can retry again.
  function retryPreviewFetch() {
    if (!pendingParams || !pendingPerQuestionParams || stalePreviewIndices.size === 0 || previewRefetchLoading) return;
    const seq = ++previewRefetchSeqRef.current;
    setPreviewRefetchLoading(true);
    const formParams = {
      ...pendingParams,
      per_question_params: JSON.stringify(pendingPerQuestionParams),
    };
    const fetchParams = toGenerateParams(subject, formParams);
    const op = useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
    void previewGenerate(fetchParams)
      .then(({ prompts }) => {
        if (seq !== previewRefetchSeqRef.current) {
          op.end("superseded");
          return;
        }
        op.end("completed");
        if (isValidPromptPreviewResponse(prompts)) {
          setPromptPreviews(prompts);
        }
        setPreviewRefetchLoading(false);
        setStalePreviewIndices(new Set());
      })
      .catch(() => {
        if (seq !== previewRefetchSeqRef.current) {
          op.end("superseded");
          return;
        }
        op.end("failed");
        setPreviewRefetchLoading(false);
        // Leave stale badge in place so the user can retry again
      });
  }

  function updatePendingSubquestionLp(
    questionIndex: number,
    subquestionIndex: number,
    lp: string[],
  ) {
    if (lp.length > 0) {
      updatePendingSubquestionConfig(questionIndex, subquestionIndex, {
        learning_performance: lp,
      });
      return;
    }
    resubmitSubquestionResolution(questionIndex, subquestionIndex, "learning_performance");
  }

  function acknowledgeRecoveryBanner() {
    const result = onRecoveryAcknowledge?.();
    if (result !== false) setRecoveryBannerDismissed(true);
  }

  function discardRecoveryBanner() {
    const result = onRecoveryDiscard?.();
    if (result !== false) setRecoveryBannerDismissed(true);
  }

  const recoveryBanner = showRecoveryBanner ? (
    <section
      role="status"
      className="sentry-unmask rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
    >
      <p className="font-medium">
        {pendingParams
          ? t("recovery.banner.confirmation_title")
          : t("recovery.banner.title")}
      </p>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={acknowledgeRecoveryBanner}
          className="underline cursor-pointer"
        >
          {t("recovery.banner.acknowledge")}
        </button>
        <button
          type="button"
          onClick={discardRecoveryBanner}
          className="underline cursor-pointer"
        >
          {t("recovery.banner.discard")}
        </button>
      </div>
    </section>
  ) : null;

  if (pendingParams) {
    const p = pendingParams;
    const drawnPaths = Array.isArray(p.drawn) ? p.drawn : [];
    const resolvedPerQuestionParams = pendingPerQuestionParams ?? parsePerQuestionParams(p.per_question_params);
    const allLpEntries = schemas?.學習表現 ?? [];
    const allLcEntries = schemas?.學習內容 ?? [];
    const lcEntryByCode = new Map(allLcEntries.map((e) => [e.value, e]));
    const lpEntryByCode = new Map(allLpEntries.map((e) => [e.value, e]));
    const subjectFilterDisplay = Array.isArray(p.subject_filter)
      ? p.subject_filter.join(", ")
      : p.subject_filter;

    const allSubjects = ["math", "social_studies", "natural_sciences"];
    const rows = ([
      { label: t("form.confirm_topic"), value: p.topic, subjects: allSubjects, kind: "absent" },
      {
        label: t("form.confirm_text_instruction"),
        value: p.text_instruction,
        subjects: ["social_studies"],
        kind: "absent",
      },
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
      { label: t("form.confirm_subject_filter"), value: subjectFilterDisplay, subjects: ["math", "social_studies"], kind: subject === "social_studies" ? "sampled" : "absent" },
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
      {
        label: t("form.confirm_allow_duplicate_figure_kinds"),
        value: p.allow_duplicate_figure_kinds ? t("form.confirm_yes") : undefined,
        subjects: ["social_studies", "natural_sciences"],
        kind: "defaulted",
        defaultValue: undefined,
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
    const drawnValueLabels = {
      "內容領域": t("form.confirm_content_domain"),
      reporting_scale: t("form.confirm_reporting_scale"),
      "核心素養": t("form.confirm_core_competency"),
      "數學思考": t("form.confirm_math_thinking"),
      "認知歷程": t("form.confirm_subq_cognitive_process").replace(/[：:]\s*$/, ""),
    };
    const valueForDrawnPath = (path: string): unknown =>
      readConfirmationPathValue(path, p as Record<string, unknown>, resolvedPerQuestionParams);
    const sharedContentDomainValue = valueForDrawnPath("內容領域");
    const hasSharedContentDomain = subject === "social_studies" && (
      (sharedContentDomainValue !== undefined && sharedContentDomainValue !== "") ||
      drawnPaths.includes("內容領域")
    );

    return (
      <div className="space-y-4">
        <ConfirmationParticipation exportWorkspace={exportConfirmation} />
        {recoveryBanner}
        <div>
          <h2 className="text-base font-semibold">{t("form.confirm_title")}</h2>
          <p className="mt-1 text-sm text-gray-500">{t("form.confirm_subtitle")}</p>
        </div>
        {resolverLoading && (
          <p role="status" aria-live="polite" className="text-sm text-amber-700">
            {t("form.confirm_resolve_loading")}
          </p>
        )}
        {resolverError && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
            <span>{t("form.confirm_resolve_error")} {resolverError}</span>
            <button
              type="button"
              onClick={retryResolver}
              disabled={resolverLoading}
              className="rounded border border-red-300 bg-white px-2 py-1 font-medium hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("form.confirm_resolve_retry")}
            </button>
          </div>
        )}
        {confirmationInvalidFields.size > 0 && (
          <p role="alert" className="sentry-unmask text-sm text-red-700">
            {t("recovery.confirmation_invalid_fields")}
          </p>
        )}
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
            {hasSharedContentDomain && (
              <DrawnValueRows
                drawnPaths={drawnPaths.filter((path) => path === "內容領域" || path === "content_domain")}
                fieldLabels={drawnValueLabels}
                alwaysPaths={["內容領域"]}
                valueForPath={valueForDrawnPath}
                renderEditor={(path, value) => path === "內容領域" ? (
                  <ConfirmationSingleSelect
                    label={t("form.confirm_content_domain")}
                    value={value}
                    entries={schemas?.內容領域 ?? []}
                    onChange={(next) => updatePendingConfirmationField(0, "content_domain", next)}
                  />
                ) : undefined}
                canEdit={(path) => path === "內容領域"}
                onRedraw={(path) => {
                  if (path === "內容領域") updatePendingConfirmationField(0, "content_domain", undefined, true);
                }}
                canRedraw={(path) => path === "內容領域"}
                editLabel={t("form.confirm_edit")}
                redrawLabel={t("form.confirm_redraw")}
                clearedPaths={clearedPaths}
                clearedNotice={t("form.confirm_cleared_notice")}
                emptyValue={t("form.confirm_not_filled")}
                drawnBadge={t("form.confirm_badge_random")}
                pinnedBadge={t("form.confirm_badge_user")}
              />
            )}
            {subject === "natural_sciences" && (
              <DrawnValueRows
                drawnPaths={drawnPaths}
                fieldLabels={drawnValueLabels}
                pathPrefix="reporting_scale"
                alwaysPaths={["reporting_scale"]}
                valueForPath={valueForDrawnPath}
                renderEditor={(path, value) => path === "reporting_scale" ? (
                  <ConfirmationSingleSelect
                    label={t("form.confirm_reporting_scale")}
                    value={value}
                    entries={schemas?.reporting_scale ?? [
                      ...["1c", "1b", "1a", "2", "3", "4", "5", "6"].map((level) => ({ value: level, instruction: "" })),
                    ]}
                    onChange={(next) => updatePendingConfirmationField(0, "reporting_scale", next)}
                  />
                ) : undefined}
                canEdit={(path) => path === "reporting_scale"}
                onRedraw={(path) => {
                  if (path === "reporting_scale") updatePendingConfirmationField(0, "reporting_scale", undefined, true);
                }}
                canRedraw={(path) => path === "reporting_scale"}
                editLabel={t("form.confirm_edit")}
                redrawLabel={t("form.confirm_redraw")}
                clearedPaths={clearedPaths}
                clearedNotice={t("form.confirm_cleared_notice")}
                emptyValue={t("form.confirm_reporting_scale_per_subquestion")}
                drawnBadge={t("form.confirm_badge_random")}
                pinnedBadge={t("form.confirm_badge_user")}
              />
            )}
          </dl>
        </section>
        {previewRefetchLoading && (
          <p className="text-sm text-amber-700">{t("form.confirm_preview_loading")}</p>
        )}
        <div className="space-y-4">
          {resolvedPerQuestionParams.map((questionParams, index) => {
            const heading = t("form.confirm_question_block").replace("{n}", String(index + 1));
            const questionLpValues = Array.isArray(questionParams.learning_performance) &&
              questionParams.learning_performance.length > 0
              ? questionParams.learning_performance
              : index === 0
                ? p.learning_performance
                : undefined;
            const questionLcValues = Array.isArray(questionParams.learning_content) &&
              questionParams.learning_content.length > 0
              ? questionParams.learning_content
              : index === 0
                ? p.learning_content
                : undefined;
            const questionLpCodes = Array.isArray(questionLpValues)
              ? questionLpValues.filter((code): code is string => typeof code === "string")
              : [];
            const questionLcCodes = Array.isArray(questionLcValues)
              ? questionLcValues.filter((code): code is string => typeof code === "string")
              : [];
            const resolvedQuestionSubject = Array.isArray(questionParams.subject_filter)
              ? questionParams.subject_filter.filter((value): value is string => typeof value === "string")
              : typeof questionParams.subject_filter === "string"
                ? questionParams.subject_filter
                : p.subject_filter;
            const allCurriculumSubjectValues = schemas?.科目?.map((entry) => entry.value) ?? [];
            const questionLpEntriesBySubject = filterCurriculumEntriesBySubject(
              allLpEntries,
              subject,
              resolvedQuestionSubject,
              allCurriculumSubjectValues,
            );
            const questionLcEntriesBySubject = filterCurriculumEntriesBySubject(
              allLcEntries,
              subject,
              resolvedQuestionSubject,
              allCurriculumSubjectValues,
            );
            const questionContentDomain = typeof questionParams.content_domain === "string"
              ? questionParams.content_domain
              : typeof p.content_domain === "string"
                ? p.content_domain
                : undefined;
            const questionLpEntries = filterLearningContentEntriesByDomain(
              questionLpEntriesBySubject,
              subject,
              resolvedQuestionSubject,
              questionContentDomain,
              schemas?.內容領域_mapping,
            );
            const questionLcEntries = filterLearningContentEntriesByDomain(
              questionLcEntriesBySubject,
              subject,
              resolvedQuestionSubject,
              questionContentDomain,
              schemas?.內容領域_mapping,
            );
            const questionLpDisplayEntries = entriesForValues(questionLpEntries, questionLpCodes);
            const questionLcDisplayEntries = entriesForValues(questionLcEntries, questionLcCodes);
            const questionSubquestionConfigs = parseSubquestionConfigs(
              questionParams.subquestion_configs,
            ) as ResolvedSubQuestionConfig[];
            const questionSubQuestionCount = typeof questionParams.sub_question_count === "number"
              ? questionParams.sub_question_count
              : index === 0 && typeof p.sub_question_count === "number"
                ? p.sub_question_count
                : undefined;
            const questionSubQuestionCountWasDrawn = resolverDrewField(
              drawnPaths,
              index,
              "sub_question_count",
            );
            const questionPathPrefix = `per_question_params[${index}].`;
            const questionDrawnPaths = drawnPaths.filter((path) =>
              path.startsWith(questionPathPrefix) ||
                (index === 0 && !path.startsWith("per_question_params[")),
            ).map((path) =>
              index === 0 && !path.startsWith("per_question_params[")
                ? `${questionPathPrefix}${path}`
                : path,
            );
            const alwaysDrawnValuePaths = [
              ...(subject === "social_studies"
                ? [`${questionPathPrefix}內容領域`]
                : []),
              ...(subject === "math" || subject === "social_studies"
                ? [`${questionPathPrefix}核心素養`]
                : []),
              ...(subject === "math" ? [`${questionPathPrefix}數學思考`] : []),
            ].filter((path) => valueForDrawnPath(path) !== undefined || questionDrawnPaths.includes(path));
            const questionLevelDrawnPaths = questionDrawnPaths.filter((path) =>
              !path.includes(".subquestion_configs[") &&
              !path.endsWith(".sub_question_count") &&
              !(subject === "natural_sciences" && path.endsWith(".reporting_scale")),
            );
            const renderConfirmationEditor = (
              key: string,
              value: unknown,
            ): ReactNode | undefined => {
              switch (key) {
                case "style":
                  return (
                    <ConfirmationSingleSelect
                      label={t("form.confirm_style")}
                      value={Array.isArray(value) ? value[0] : value}
                      entries={schemas?.question_style ?? []}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                case "content_type":
                  return (
                    <ConfirmationSingleSelect
                      label={t("form.confirm_content_type")}
                      value={value}
                      entries={schemas?.題目內容類型 ?? []}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                case "context": {
                  const current = Array.isArray(value) ? value : [];
                  return (
                    <ConfirmationMultiSelect
                      label={t("form.confirm_context")}
                      value={current}
                      entries={schemas?.情境 ?? []}
                      max={subject === "natural_sciences" ? 1 : schemas?.情境.length ?? 1}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                }
                case "set_type":
                  return (
                    <ConfirmationSingleSelect
                      label={t("form.confirm_set_type")}
                      value={value}
                      entries={schemas?.題型種類 ?? []}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                case "q_type":
                  return (
                    <ConfirmationMultiSelect
                      label={t("form.confirm_q_type")}
                      value={value}
                      entries={availableQuestionTypes}
                      max={availableQuestionTypes.length || 1}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                case "subject_filter": {
                  const current = Array.isArray(value) ? value : [];
                  return (
                    <ConfirmationMultiSelect
                      label={t("form.confirm_subject_filter")}
                      value={current}
                      entries={schemas?.科目 ?? []}
                      max={1}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                }
                case "sub_context": {
                  const currentContext = Array.isArray(questionParams.context)
                    ? questionParams.context
                    : typeof questionParams.context === "string"
                      ? [questionParams.context]
                      : [];
                  const entries = filterEntriesByAdmittedParent(
                    schemas?.情境子類別 ?? [],
                    "情境",
                    currentContext,
                  );
                  return (
                    <ConfirmationSingleSelect
                      label={t("form.confirm_sub_context")}
                      value={value}
                      entries={entries}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                }
                case "science_competency":
                  return (
                    <ConfirmationMultiSelect
                      label={t("form.confirm_science_competency")}
                      value={value}
                      entries={schemas?.科學能力 ?? []}
                      max={2}
                      onChange={(next) => updatePendingConfirmationField(index, key, next)}
                    />
                  );
                default:
                  return undefined;
              }
            };
            const questionLpWasDrawn = resolverDrewField(drawnPaths, index, "learning_performance");
            const questionLcWasDrawn = resolverDrewField(drawnPaths, index, "learning_content");
            const questionLpHeading = t(
              questionLpWasDrawn ? "form.confirm_lp_random_pool" : "form.confirm_lp_selected",
            )
              .replace("{n}", String(questionLpDisplayEntries.length));
            const questionLcHeading = t(
              questionLcWasDrawn ? "form.confirm_lc_random_pool" : "form.confirm_lc_selected",
            )
              .replace("{n}", String(questionLcDisplayEntries.length));
            // Per-question effective text_instruction: row-level override (釘選) or
            // request-level fallback.  Prefills the editable 確認頁修改 field. (#637)
            const questionTextInstructionOverride =
              typeof questionParams.text_instruction === "string" &&
              questionParams.text_instruction.trim() !== ""
                ? questionParams.text_instruction
                : null;
            const effectiveQuestionTextInstruction =
              questionTextInstructionOverride ??
              (typeof p.text_instruction === "string" ? p.text_instruction : "");

            const textGeneratorPreview = promptPreviews.find(
              (preview) => preview.index === index && preview.subquestion_index === undefined,
            );
            const subquestionGeneratorPreviews = promptPreviews
              .filter(
                (preview) => preview.index === index && preview.subquestion_index !== undefined,
              )
              .sort((a, b) => a.subquestion_index! - b.subquestion_index!);
            // #446: stale badge — true when this 題組's preview is out of date
            // due to a failed re-fetch triggered by a 確認頁修改 on this 題組.
            const isStale = stalePreviewIndices.has(index);
            return (
              <section
                key={index}
                role="region"
                aria-label={heading}
                className="rounded-lg border border-gray-200 bg-white p-4"
              >
                <h3 className="mb-3 font-semibold text-gray-800">{heading}</h3>
                {isStale && (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-amber-700">
                      {t("form.confirm_preview_stale_badge")}
                    </span>
                    <button
                      type="button"
                      onClick={retryPreviewFetch}
                      disabled={previewRefetchLoading}
                      className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {t("form.confirm_preview_retry")}
                    </button>
                  </div>
                )}
                {questionSubQuestionCount !== undefined && (
                  <dl className="mb-3">
                    <div
                      className="flex gap-3 text-sm"
                      data-drawn-value-path={`${questionPathPrefix}sub_question_count`}
                    >
                      <dt className="w-40 shrink-0 font-medium text-gray-600">
                        {t("form.confirm_sub_question_count")}
                      </dt>
                      <dd className="min-w-0 flex-1 break-words text-gray-900">
                        <span>{questionSubQuestionCount}</span>
                        <span className={`ml-2 text-xs font-medium ${questionSubQuestionCountWasDrawn ? "text-amber-700" : "text-green-700"}`}>
                          {t(questionSubQuestionCountWasDrawn ? "form.confirm_badge_random" : "form.confirm_badge_user")}
                        </span>
                        {questionSubQuestionCountWasDrawn && (
                          <ConfirmationRowActions
                            isRandom
                            editor={() => (
                              <ConfirmationSubQuestionCountInput
                                value={questionSubQuestionCount}
                                onChange={(next) => updatePendingConfirmationField(
                                  index,
                                  "sub_question_count",
                                  next,
                                )}
                              />
                            )}
                            onRedraw={() => updatePendingConfirmationField(
                              index,
                              "sub_question_count",
                              undefined,
                              true,
                            )}
                            editLabel={t("form.confirm_edit")}
                            redrawLabel={t("form.confirm_redraw")}
                          />
                        )}
                        {clearedPaths.includes(`${questionPathPrefix}sub_question_count`) && (
                          <span className="ml-2 text-xs font-medium text-amber-700">
                            {t("form.confirm_cleared_notice")}
                          </span>
                        )}
                      </dd>
                    </div>
                  </dl>
                )}
                {/* Per-題組 文本出題指示 確認頁修改 (#637) */}
                {(subject === "social_studies" || subject === "natural_sciences") && (
                  <div className="mb-3 flex gap-3 text-sm">
                    <label
                      htmlFor={`confirm-text-instruction-${index}`}
                      className="w-40 shrink-0 font-medium text-gray-600"
                    >
                      {t("form.confirm_text_instruction")}
                    </label>
                    <div className="min-w-0 flex-1">
                      <textarea
                        id={`confirm-text-instruction-${index}`}
                        aria-label={t("form.confirm_text_instruction")}
                        value={effectiveQuestionTextInstruction}
                        onChange={(e) =>
                          updatePendingQuestionTextInstruction(index, e.target.value)
                        }
                        rows={2}
                        placeholder={t("form.text_instruction_placeholder")}
                        className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>
                )}
                <dl className="space-y-2">
                  {perQuestionRows.map(({ key, label }) => {
                      const value = questionParams[key];
                      const displayValue = Array.isArray(value)
                        ? value.join(", ")
                        : value === undefined
                          ? undefined
                          : String(value);
                      const isRandom = resolverDrewField(drawnPaths, index, key);
                      const isPredrawnSeed = key === "seed" && isRandom;
                      const rowPath = `${questionPathPrefix}${RESOLVER_FIELD_ALIASES[key] ?? key}`;
                      const editor = key === "seed"
                        ? undefined
                        : () => renderConfirmationEditor(key, value);
                      return (
                        <div key={key} className="flex gap-3 text-sm" data-drawn-value-path={rowPath}>
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
                            {clearedPaths.includes(rowPath) && (
                              <span className="ml-2 text-xs font-medium text-amber-700">
                                {t("form.confirm_cleared_notice")}
                              </span>
                            )}
                            <ConfirmationRowActions
                              isRandom={isRandom && !isPredrawnSeed}
                              editor={editor}
                              onRedraw={key === "seed"
                                ? undefined
                                : () => updatePendingConfirmationField(index, key, undefined, true)}
                              editLabel={t("form.confirm_edit")}
                              redrawLabel={t("form.confirm_redraw")}
                            />
                          </dd>
                        </div>
                      );
                    })}
                  <DrawnValueRows
                    drawnPaths={questionLevelDrawnPaths}
                    fieldLabels={drawnValueLabels}
                    alwaysPaths={alwaysDrawnValuePaths}
                    valueForPath={valueForDrawnPath}
                    renderEditor={(path, value) => {
                      const field = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
                      if (field === "內容領域") {
                        return (
                          <ConfirmationSingleSelect
                            label={t("form.confirm_content_domain")}
                            value={value}
                            entries={schemas?.內容領域 ?? []}
                            onChange={(next) => updatePendingConfirmationField(index, "content_domain", next)}
                          />
                        );
                      }
                      if (field === "核心素養" || field === "數學思考") {
                        const selected = Array.isArray(value)
                          ? value.filter((item): item is string => typeof item === "string")
                          : [];
                        const entries = field === "核心素養"
                          ? schemas?.核心素養 ?? []
                          : schemas?.數學思考 ?? [];
                        return (
                          <ConfirmationMultiSelect
                            label={field === "核心素養"
                              ? t("form.confirm_core_competency")
                              : t("form.confirm_math_thinking")}
                            value={selected}
                            entries={entries}
                            max={3}
                            onChange={(next) => updatePendingConfirmationField(
                              index,
                              field === "核心素養" ? "core_competency" : "math_thinking",
                              next,
                            )}
                          />
                        );
                      }
                      return undefined;
                    }}
                    canEdit={(path) => {
                      const field = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
                      return field === "內容領域" || field === "核心素養" || field === "數學思考";
                    }}
                    onRedraw={(path) => {
                      const field = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
                      const key = field === "內容領域"
                        ? "content_domain"
                        : field === "數學思考" ? "math_thinking" : "core_competency";
                      updatePendingConfirmationField(index, key, undefined, true);
                    }}
                    canRedraw={(path) => {
                      const field = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
                      return field === "內容領域" || field === "核心素養" || field === "數學思考";
                    }}
                    editLabel={t("form.confirm_edit")}
                    redrawLabel={t("form.confirm_redraw")}
                    clearedPaths={clearedPaths}
                    clearedNotice={t("form.confirm_cleared_notice")}
                    emptyValue={t("form.confirm_not_filled")}
                    drawnBadge={t("form.confirm_badge_random")}
                    pinnedBadge={t("form.confirm_badge_user")}
                    compact={(path) => path.endsWith("內容領域")}
                  />
                  <div
                    className="flex gap-3 text-sm"
                    data-drawn-value-path={`${questionPathPrefix}學習表現`}
                  >
                      <dt className="w-40 shrink-0 font-medium text-gray-600">{t("form.confirm_learning_performance")}</dt>
                      <dd className="min-w-0 flex-1 text-gray-900">
                        {questionLpDisplayEntries.length === 0 ? (
                          <span className="italic text-gray-400">{t("form.confirm_not_filled")}</span>
                        ) : (
                          <div className="space-y-1">
                            <p className={`mb-1.5 text-xs font-medium ${questionLpWasDrawn ? "text-amber-700" : "text-green-700"}`}>{questionLpHeading}</p>
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
                        {questionLpWasDrawn && (
                          <ConfirmationRowActions
                            isRandom
                            editor={() => (
                              <ConfirmationMultiSelect
                                label={t("form.confirm_learning_performance")}
                                value={questionLpCodes}
                                entries={questionLpEntries}
                                max={subject === "math" ? 3 : 2}
                                onChange={(next) => updatePendingConfirmationField(
                                  index,
                                  "learning_performance",
                                  next,
                                )}
                              />
                            )}
                            onRedraw={() => updatePendingConfirmationField(
                              index,
                              "learning_performance",
                              undefined,
                              true,
                            )}
                            editLabel={t("form.confirm_edit")}
                            redrawLabel={t("form.confirm_redraw")}
                          />
                        )}
                        {clearedPaths.includes(`${questionPathPrefix}學習表現`) && (
                          <span className="ml-2 text-xs font-medium text-amber-700">
                            {t("form.confirm_cleared_notice")}
                          </span>
                        )}
                      </dd>
                  </div>
                  <div
                    className="flex gap-3 text-sm"
                    data-drawn-value-path={`${questionPathPrefix}學習內容`}
                  >
                      <dt className="w-40 shrink-0 font-medium text-gray-600">{t("form.confirm_learning_content")}</dt>
                      <dd className="min-w-0 flex-1 text-gray-900">
                        {questionLcDisplayEntries.length === 0 ? (
                          <span className="italic text-gray-400">
                            {t("form.confirm_not_filled")}
                          </span>
                        ) : (
                          <div className="space-y-1">
                            <p className={`mb-1.5 text-xs font-medium ${questionLcWasDrawn ? "text-amber-700" : "text-green-700"}`}>{questionLcHeading}</p>
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
                        {questionLcWasDrawn && (
                          <ConfirmationRowActions
                            isRandom
                            editor={() => (
                              <ConfirmationMultiSelect
                                label={t("form.confirm_learning_content")}
                                value={questionLcCodes}
                                entries={questionLcEntries}
                                max={3}
                                onChange={(next) => updatePendingConfirmationField(
                                  index,
                                  "learning_content",
                                  next,
                                )}
                              />
                            )}
                            onRedraw={() => updatePendingConfirmationField(
                              index,
                              "learning_content",
                              undefined,
                              true,
                            )}
                            editLabel={t("form.confirm_edit")}
                            redrawLabel={t("form.confirm_redraw")}
                          />
                        )}
                        {clearedPaths.includes(`${questionPathPrefix}學習內容`) && (
                          <span className="ml-2 text-xs font-medium text-amber-700">
                            {t("form.confirm_cleared_notice")}
                          </span>
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
                      questionIndex={index}
                      drawnPaths={drawnPaths}
                      drawnValueLabels={drawnValueLabels}
                      cognitiveProcesses={schemas?.認知歷程 ?? []}
                      reportingScales={schemas?.reporting_scale}
                      clearedPaths={clearedPaths}
                      showContentDomain={false}
                      questionTypes={availableQuestionTypes}
                      contentTypes={schemas?.題目內容類型 ?? []}
                      lcEntryByCode={lcEntryByCode}
                      lpEntryByCode={lpEntryByCode}
                      availableLc={questionLcEntries}
                      availableLp={questionLpEntries}
                      onInstructionChange={(subquestionIndex, instruction) =>
                        updatePendingSubquestionInstruction(index, subquestionIndex, instruction)
                      }
                      onQuestionTypeChange={(subquestionIndex, questionType) =>
                        updatePendingSubquestionQuestionType(index, subquestionIndex, questionType)
                      }
                      onContentTypeChange={(subquestionIndex, contentType) =>
                        updatePendingSubquestionContentType(index, subquestionIndex, contentType)
                      }
                      onImageModeChange={(subquestionIndex, imageMode) =>
                        updatePendingSubquestionImageMode(index, subquestionIndex, imageMode)
                      }
                      onReportingScaleChange={(subquestionIndex, reportingScale) =>
                        updatePendingSubquestionReportingScale(index, subquestionIndex, reportingScale)
                      }
                      onCognitiveProcessChange={(subquestionIndex, cognitiveProcess) =>
                        updatePendingSubquestionCognitiveProcess(index, subquestionIndex, cognitiveProcess)
                      }
                      onQuestionWordLimitChange={(subquestionIndex, value) =>
                        updatePendingSubquestionQuestionWordLimit(index, subquestionIndex, value)
                      }
                      onOptionWordLimitChange={(subquestionIndex, value) =>
                        updatePendingSubquestionOptionWordLimit(index, subquestionIndex, value)
                      }
                      onFieldValidityChange={(subquestionIndex, fieldKey, isValid) =>
                        setConfirmFieldValidity(index, subquestionIndex, fieldKey, isValid)
                      }
                      onLcChange={(subquestionIndex, lc) =>
                        updatePendingSubquestionLc(index, subquestionIndex, lc)
                      }
                      onLpChange={(subquestionIndex, lp) =>
                        updatePendingSubquestionLp(index, subquestionIndex, lp)
                      }
                      onFieldRedraw={(subquestionIndex, field) =>
                        resubmitSubquestionField(index, subquestionIndex, field)
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
            disabled={disabled || resolverLoading || resolverError !== null || confirmationHydrating ||
              (recoveryConfirmation !== undefined && coreQuestionResolution === "loading") ||
              confirmationHasInvalidFields}
            className="inline-flex items-center gap-2 rounded bg-blue-600 px-5 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("form.btn_confirm_send")}
          </button>
          <div className="flex flex-col items-start">
            <button
              type="button"
              onClick={() => {
                resolveRequestSeqRef.current += 1;
                resolveOperationRef.current?.end("superseded");
                resolveOperationRef.current = null;
                resolveRequestRef.current = null;
                pendingParamsRef.current = null;
                pendingPerQuestionParamsRef.current = null;
                setPendingParams(null);
                setPendingPerQuestionParams(null);
                setClearedPaths([]);
                setHasPendingConfirmationEdits(false);
                setConfirmInvalidFields(new Map());
                setResolverLoading(false);
                setResolverError(null);
                // #446: clear stale state when navigating back to the form
                setStalePreviewIndices(new Set());
              }}
              className="rounded border border-gray-300 bg-white px-4 py-2 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("form.btn_back_edit")}
            </button>
            {hasPendingConfirmationEdits && (
              // 確認頁修改不會寫回共用的各小題配置，因此返回表單會捨棄這些修改。
              <p className="mt-1 max-w-64 text-xs text-amber-800">
                {t("form.confirm_edit_discard_warning")}
              </p>
            )}
          </div>
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
      {recoveryBanner}
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
      {resolverLoading && (
        <p role="status" aria-live="polite" className="text-sm text-amber-700">
          {t("form.confirm_resolve_loading")}
        </p>
      )}
      {resolverError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          <span>{t("form.confirm_resolve_error")} {resolverError}</span>
          <button
            type="button"
            onClick={retryResolver}
            disabled={resolverLoading}
            className="rounded border border-red-300 bg-white px-2 py-1 font-medium hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("form.confirm_resolve_retry")}
          </button>
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
                    figureKinds={
                      (subject === "social_studies" || subject === "natural_sciences")
                        ? schemas.figure_kinds ?? []
                        : undefined
                    }
                    onChange={(patch) => updateSubquestionConfig(i, patch)}
                  />
                  <SubQuestionCurriculumPickers
                    availableLearningPerformance={availableLearningPerformance}
                    availableLearningContent={availableLearningContent}
                    filteredLpPool={filteredLpPool}
                    filteredLcPool={filteredLcPool}
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

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <div>
          <label htmlFor="text-instruction" className="block text-sm font-medium">
            {t("form.text_instruction_label")}
          </label>
          <input
            id="text-instruction"
            type="text"
            value={textInstruction}
            onChange={(e) => setField("textInstruction", e.target.value)}
            placeholder={t("form.text_instruction_placeholder")}
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

      {(subject === "social_studies" || subject === "natural_sciences") && (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={allowDuplicateFigureKinds}
            onChange={(e) => setField("allowDuplicateFigureKinds", e.target.checked)}
          />
          <span className="text-sm">{t("form.allow_duplicate_figure_kinds_label")}</span>
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

      {recoveredInvalidFields.size > 0 && (
        <p
          role="alert"
          className="sentry-unmask text-sm text-red-700"
        >
          {t("recovery.invalid_fields")}
        </p>
      )}
      <button
        type="submit"
        disabled={disabled || resolverLoading || recoveredInvalidFields.size > 0}
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
