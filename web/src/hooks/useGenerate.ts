import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import * as Sentry from "@sentry/react";

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import { isSentryEnabled } from "../sentry";
import { saveSignoutReason } from "../lib/signoutReason";
import { saveReturnDestination } from "../lib/returnDestination";
import type { GenerateParams } from "../api/generated/contract";
import { MESSAGES } from "../i18n/messages";
import { createGenerationStreamDecoder } from "../lib/generationStream";
import {
  createRunEvidence,
  applyV2Event,
  type RunEvidenceState,
} from "../lib/generationEvidence";
import {
  formatResolverFieldErrors,
  isResolverFieldErrorLike,
} from "../lib/resolverErrorMessages";

import { useWorkspaceStore, type OperationHandle, type OperationOutcome } from "../lib/workspace/workspaceStore";
import { importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import type { ResultsCompletion, ResultsWorkspaceSnapshot } from "../lib/workspace/adapters/types";

export type { GenerateParams };

export type AdmissionState = "idle" | "submitting" | "admitted" | "rejected";
export type AdmissionOutcome = { outcome: "admitted" } | { outcome: "rejected"; reason: string };

export type GenerateStatus = "idle" | "generating" | "error";

export interface LearningContentItem {
  編碼: string;
  說明: string;
}

export interface RubricEntry {
  /** Opaque scoring-level text: new 0..N levels and legacy 2/1/0/0X both render. */
  code: string;
  規準說明: string;
  學生作答實例?: string[];
}

export interface DragDropSpec {
  draggables: Array<{ id: string; label: string }>;
  targets: Array<{ id: string; label: string; capacity: number }>;
  correct_mapping: Record<string, string>;
  exact_match: boolean;
  shuffle_draggables: boolean;
}

export interface SliderSpec {
  min: number;
  max: number;
  step: number;
  unit: string;
  correct_value: number;
  tolerance: number;
  show_ticks: boolean;
}

export interface SubQuestion {
  id: string;
  序號: number;
  年級: number;
  科目: string[];
  科學能力?: string[];
  核心素養: string[];
  學習內容: LearningContentItem[];
  學習表現: LearningContentItem[];
  認知歷程?: string;
  出題概念: string;
  題型: string;
  題目: string;
  答案: string;
  答案解析: string;
  interaction?: DragDropSpec | SliderSpec;
  評分規準?: RubricEntry[];
  誘答分析?: Record<string, string>;
  題目內容類型?: string;
  image_generation_mode?: "html" | "gpt_image";
  圖片?: string | null;
  chart_spec?: unknown;
  image_base64?: string;
}

export interface ExamQuestion {
  id?: string;
  情境: string[];
  題型種類: string;
  題型: string;
  數學思考?: string[];
  學習內容?: LearningContentItem[];
  閱讀歷程?: string[];
  文本形式?: string;
  內容領域?: string;
  認知歷程?: string[];
  題目內容類型?: string;
  情境子類別?: string;
  科學能力?: string[];
  核心問題?: string;
  文本?: string;
  subquestions?: SubQuestion[];
  題目: string[];
  正確解題分析: string[];
  出題概念?: string;
  誘答分析?: Record<string, string>;
  圖片?: string | null;
  chart_spec?: unknown;
  verification?: unknown;
  metadata?: unknown;
  image_stale?: boolean;
  image_base64?: string;
}

export interface ChartVerificationTrail {
  chart_data_match: boolean;
  chart_labels_correct: boolean;
  chart_details: string;
}

export interface VerificationTrailVerificationEntry {
  code: "verification_trail";
  kind: "verification";
  question_id: string;
  passed: boolean;
  details: string;
  my_answer: string;
  provided_answer: string;
  answer_match: boolean;
  chart_verification: ChartVerificationTrail | null;
  model: string;
  timestamp: string;
}

export interface VerificationTrailInitialEntry {
  code: "verification_trail";
  kind: "initial";
  question_id: string;
  timestamp: string;
  snapshot: Record<string, unknown>;
}

export interface VerificationTrailCorrectionEntry {
  code: "verification_trail";
  kind: "correction";
  question_id: string;
  retry_index: number;
  model: string;
  timestamp: string;
  snapshot: Record<string, unknown>;
}

export type VerificationTrailEntry =
  | VerificationTrailVerificationEntry
  | VerificationTrailInitialEntry
  | VerificationTrailCorrectionEntry;

export interface FigurePolicySpecEntry {
  code: "figure_policy";
  kind: "spec";
  question_id: string;
  label: string;
  effective_figure_kind: string;
  timestamp: string;
}

export interface FigurePolicyCollisionEntry {
  code: "figure_policy";
  kind: "collision";
  question_id: string;
  left: string;
  right: string;
  effective_figure_kind: string;
  timestamp: string;
}

export interface FigurePolicyRepairEntry {
  code: "figure_policy";
  kind: "repair";
  question_id: string;
  target: string;
  before_effective_figure_kind: string;
  after_effective_figure_kind: string;
  forbidden_kinds: string[];
  succeeded: boolean;
  error?: string | null;
  timestamp: string;
}

export interface FigurePolicyWarningEntry {
  code: "figure_policy";
  kind: "warning";
  question_id: string;
  message: string;
  duplicate_image_shipped: boolean;
  left?: string | null;
  right?: string | null;
  effective_figure_kind?: string | null;
  timestamp: string;
}

export interface FigurePolicyDataInconsistencyEntry {
  code: "figure_policy";
  kind: "data_inconsistency";
  question_id: string;
  left: string;
  right: string;
  series: string;
  x: unknown;
  left_value: number;
  right_value: number;
  conflicting_values: Record<string, number>;
  unit: string;
  duplicate_image_shipped: boolean;
  message: string;
  timestamp: string;
}

export type FigurePolicyTrailEntry =
  | FigurePolicySpecEntry
  | FigurePolicyCollisionEntry
  | FigurePolicyRepairEntry
  | FigurePolicyWarningEntry
  | FigurePolicyDataInconsistencyEntry;

export interface ReferenceExampleEntryShape {
  code: "reference_example";
  kind: "example" | "process_exemplar";
  question_id: string;
  stage: string;
  slot?: number | null;
  description?: string;
  source: string;
  content?: unknown;
  images?: Array<{ path: string; description?: string }>;
  cognitive_process?: string;
  timestamp: string;
}

export interface ReferenceExampleRecordShape {
  disabled?: boolean;
  entries: ReferenceExampleEntryShape[];
}

export type DraftPhase = "draft" | "image" | "verified" | "corrected";

export interface GeneratedQuestion {
  index: number;
  question: ExamQuestion;
  phase: DraftPhase;
  isFinal: boolean;
  /** Stable server identity/content revision when the stream provides them. */
  stableId?: string;
  contentRevision?: number | null;
  trail?: VerificationTrailEntry[];
  figurePolicyTrail?: FigurePolicyTrailEntry[];
  referenceExampleRecord?: ReferenceExampleRecordShape;
}

export type LlmCallEvent =
  | { type: "request"; purpose: string; agent: string; model: string; messages: unknown[]; params?: unknown }
  | { type: "thinking"; purpose: string; agent: string; text: string }
  | { type: "content"; purpose: string; agent: string; text: string }
  | { type: "response"; purpose: string; agent: string; model: string; usage?: unknown }
  | { type: "stage"; agent: string; stage: string; status: "start" | "end" | "error"; ts: number; retry?: number; message?: string };

export type StageEvent = Extract<LlmCallEvent, { type: "stage" }>;

export type AgentStatus = "idle" | "running" | "done" | "error";

export interface AgentLane {
  agent: string;
  status: AgentStatus;
  currentStage: string | null;
  streamingThinking: string;
  streamingContent: string;
  stageHistory: Array<{ stage: string; startedAt: number; endedAt?: number; retry?: number }>;
  errorMessage?: string;
}

/** Payload announced before a generation stream starts doing model work. */
export interface StartedEventPayload {
  generation_log_id: string | null;
}

function purposeToAgent(purpose: string): string {
  const map: Record<string, string> = {
    generate: "generator",
    verify: "verifier",
    correct: "corrector",
    html_image: "image_agent",
    gpt_image: "image_agent",
    plan: "planner",
    plan_core_questions: "planner",
    plan_context_angles: "planner",
  };
  return map[purpose] ?? purpose;
}

export interface UseGenerateReturn {
  status: GenerateStatus;
  progressLines: string[];
  results: ExamQuestion[];
  displayResults: GeneratedQuestion[];
  evidence: RunEvidenceState | null;
  llmCalls: LlmCallEvent[];
  agentLanes: AgentLane[];
  errorMessage: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  generationLogId: string | null;
  subQuestionTotal: number | null;
  admission: AdmissionState;
  admissionError: string | null;
  /** Optional for callers that do not render recovery status (legacy mocks). */
  resultsCompletion?: ResultsCompletion | null;
  terminalEvidence?: boolean;
  generate: (params: GenerateParams) => Promise<AdmissionOutcome>;
  restoreResults: (snapshot: ResultsWorkspaceSnapshot) => boolean;
  reset: () => void;
}

class FatalStreamError extends Error {}

function questionKey(question: ExamQuestion, index: number): string {
  return question.id && question.id.length > 0 ? question.id : `index-${index}`;
}

function upsertDisplayResult(
  prev: GeneratedQuestion[],
  next: GeneratedQuestion,
): GeneratedQuestion[] {
  const key = questionKey(next.question, next.index);
  const existingIndex = prev.findIndex((item) => (
    questionKey(item.question, item.index) === key || item.index === next.index
  ));
  if (existingIndex === -1) {
    return [...prev, next].sort((a, b) => a.index - b.index);
  }
  const updated = [...prev];
  updated[existingIndex] = next;
  return updated.sort((a, b) => a.index - b.index);
}

/**
 * Parse an SSE error event's raw data string into a human-readable message.
 *
 * The server now emits structured JSON: `{"code": "...", "message": "..."}`.
 * Older or third-party error sources may still send a plain string.  This
 * helper handles both so the UI always has something useful to display.
 *
 * Rules:
 * - Valid JSON with a non-empty `.message` string → return `.message`.
 * - Anything else (invalid JSON, missing/non-string message) → return the
 *   raw string unchanged, or "Unknown error" when the raw string is empty.
 */
export function parseErrorEventData(raw: string): string {
  if (!raw) return "Unknown error";
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "message" in parsed &&
      typeof (parsed as Record<string, unknown>).message === "string" &&
      (parsed as Record<string, unknown>).message !== ""
    ) {
      return (parsed as Record<string, string>).message;
    }
  } catch {
    // not JSON — fall through
  }
  return raw;
}

/** Parse the typed started-event payload while accepting legacy empty payloads. */
export function parseStartedEventData(raw: string): StartedEventPayload | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed === null || typeof parsed !== "object") return null;
    const generationLogId = (parsed as Record<string, unknown>).generation_log_id;
    if (typeof generationLogId === "string" || generationLogId === null) {
      return { generation_log_id: generationLogId };
    }
  } catch {
    // Legacy and third-party streams may send an empty or non-JSON payload.
  }
  return null;
}

function formatHttpErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail !== "") return detail;
  if (!Array.isArray(detail)) return null;

  const fieldErrors = detail.filter(isResolverFieldErrorLike);
  if (fieldErrors.length > 0) {
    // #835: incompatible_parent / no_admitting_parent get a readable
    // sentence via the shared formatter; `unresolved` (and any other/
    // unknown code) keeps its pre-#835 "field (code)" text — the formatter
    // returns null for a batch containing any of those, and this falls
    // back to the original join.
    const lang = useLangStore.getState().lang;
    const readable = formatResolverFieldErrors(fieldErrors, lang);
    if (readable !== null) return readable;
    return `Incomplete request: ${fieldErrors
      .map(({ field, code }) => `${field} (${code})`)
      .join("; ")}`;
  }

  const validationErrors = detail.flatMap((item: unknown) => {
    if (item === null || typeof item !== "object") return [];
    const { loc, msg } = item as Record<string, unknown>;
    if (!Array.isArray(loc) || typeof msg !== "string" || msg === "") return [];
    if (!loc.every((part) => typeof part === "string" || Number.isInteger(part))) return [];
    const path = loc[0] === "body" || loc[0] === "query" ? loc.slice(1) : loc;
    const field = path.reduce<string>((address, part) => (
      typeof part === "number" ? `${address}[${part}]` : `${address}${address ? "." : ""}${part}`
    ), "");
    // Only select location/message; input and ctx may contain submitted content.
    return [field ? `${field}: ${msg}` : msg];
  });
  return validationErrors.length > 0 ? `Invalid request: ${validationErrors.join("; ")}` : null;
}

export function buildQueryString(params: GenerateParams): string {
  const qs = new URLSearchParams();
  qs.append("stream_version", "2");
  if (params.subject !== undefined) qs.append("subject", params.subject);
  if (params.grade !== undefined) qs.append("grade", String(params.grade));
  if (params.content_type !== undefined) qs.append("content_type", params.content_type);
  if (params.set_type !== undefined) qs.append("set_type", params.set_type);
  if (params.count !== undefined) qs.append("count", String(params.count));
  if (params.skip_verify !== undefined) qs.append("skip_verify", String(params.skip_verify));
  if (params.disable_reference_fewshot !== undefined) {
    qs.append("disable_reference_fewshot", String(params.disable_reference_fewshot));
  }
  if (params.seed !== undefined) qs.append("seed", String(params.seed));
  if (params.image_generation_mode !== undefined) {
    qs.append("image_generation_mode", params.image_generation_mode);
  }
  for (const v of params.style ?? []) qs.append("style", v);
  for (const v of params.context ?? []) qs.append("context", v);
  for (const v of params.q_type ?? []) qs.append("q_type", v);
  for (const v of params.subject_filter ?? []) qs.append("subject_filter", v);
  if (params.content_domain) qs.append("content_domain", params.content_domain);
  if (params.target_surface) qs.append("target_surface", params.target_surface);
  if (params.passage) qs.append("passage", params.passage);
  for (const v of params.options ?? []) qs.append("options", v);
  if (params.topic) qs.append("topic", params.topic);
  if (params.core_question) qs.append("core_question", params.core_question);
  if (params.text_instruction) qs.append("text_instruction", params.text_instruction);
  if (params.sub_context) qs.append("sub_context", params.sub_context);
  for (const v of params.science_competency ?? []) qs.append("science_competency", v);
  if (params.reporting_scale) qs.append("reporting_scale", params.reporting_scale);
  for (const v of params.learning_performance ?? []) qs.append("learning_performance", v);
  for (const v of params.core_competency ?? []) qs.append("core_competency", v);
  for (const v of params.math_thinking ?? []) qs.append("math_thinking", v);
  for (const v of params.learning_content ?? []) qs.append("learning_content", v);
  if (params.sub_question_count !== undefined) qs.append("sub_question_count", String(params.sub_question_count));
  if (params.question_word_limit !== undefined) qs.append("question_word_limit", String(params.question_word_limit));
  if (params.option_word_limit !== undefined) qs.append("option_word_limit", String(params.option_word_limit));
  if (params.text_word_limit !== undefined) qs.append("text_word_limit", String(params.text_word_limit));
  if (params.subquestion_configs) qs.append("subquestion_configs", params.subquestion_configs);
  if (params.per_question_params) qs.append("per_question_params", params.per_question_params);
  for (const v of params.drawn ?? []) qs.append("drawn", v);
  if (params.difficulty !== undefined) qs.append("difficulty", params.difficulty);
  if (params.model_plan && params.model_plan.length > 0) {
    qs.append("model_plan", params.model_plan);
  }
  if (params.model_execute && params.model_execute.length > 0) {
    qs.append("model_execute", params.model_execute);
  }
  if (params.model_verify && params.model_verify.length > 0) {
    qs.append("model_verify", params.model_verify);
  }
  if (params.model_correct && params.model_correct.length > 0) {
    qs.append("model_correct", params.model_correct);
  }
  if (params.effort_plan !== undefined) qs.append("effort_plan", params.effort_plan);
  if (params.effort_execute !== undefined) qs.append("effort_execute", params.effort_execute);
  if (params.effort_verify && params.effort_verify.length > 0) {
    qs.append("effort_verify", params.effort_verify);
  }
  if (params.effort_correct && params.effort_correct.length > 0) {
    qs.append("effort_correct", params.effort_correct);
  }
  if (params.coverage_mode !== undefined) qs.append("coverage_mode", params.coverage_mode);
  if (params.core_question_callback !== undefined) {
    qs.append("core_question_callback", String(params.core_question_callback));
  }
  // Omit when false so existing requests are byte-identical (issue #450).
  if (params.allow_duplicate_figure_kinds === true) {
    qs.append("allow_duplicate_figure_kinds", "true");
  }
  return qs.toString();
}

const AGENT_ORDER = ["generator", "verifier", "corrector", "image_agent", "planner"];

function buildAgentLanes(events: LlmCallEvent[]): AgentLane[] {
  const lanesMap = new Map<string, AgentLane>();

  const getOrCreate = (agent: string): AgentLane => {
    if (!lanesMap.has(agent)) {
      lanesMap.set(agent, {
        agent,
        status: "idle",
        currentStage: null,
        streamingThinking: "",
        streamingContent: "",
        stageHistory: [],
      });
    }
    return lanesMap.get(agent)!;
  };

  for (const ev of events) {
    if (ev.type === "stage") {
      const lane = getOrCreate(ev.agent);
      if (ev.status === "start") {
        lane.status = "running";
        lane.currentStage = ev.stage;
        lane.stageHistory.push({ stage: ev.stage, startedAt: ev.ts, retry: ev.retry });
      } else if (ev.status === "error") {
        lane.status = "error";
        lane.currentStage = null;
        lane.errorMessage = ev.message;
        const last = lane.stageHistory[lane.stageHistory.length - 1];
        if (last && last.stage === ev.stage) last.endedAt = ev.ts;
      } else {
        lane.status = "done";
        lane.currentStage = null;
        const last = lane.stageHistory[lane.stageHistory.length - 1];
        if (last && last.stage === ev.stage) last.endedAt = ev.ts;
      }
    } else if (ev.type === "request") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose));
      lane.status = "running";
      lane.streamingThinking = "";
      lane.streamingContent = "";
    } else if (ev.type === "thinking") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose));
      lane.streamingThinking += ev.text;
    } else if (ev.type === "content") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose));
      lane.streamingContent += ev.text;
    } else if (ev.type === "response") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose));
      if (lane.status === "running" && !lane.currentStage) {
        lane.status = "done";
      }
    }
  }

  const laneOrder = (agent: string): [number, number] => {
    if (agent === "generator") return [0, 0];
    if (agent.startsWith("sub_generator#")) {
      const idx = Number(agent.split("#")[1]);
      return [1, Number.isFinite(idx) ? idx : Number.MAX_SAFE_INTEGER];
    }
    const orderIndex = AGENT_ORDER.indexOf(agent);
    if (orderIndex !== -1) return [2, orderIndex];
    return [3, 0];
  };

  return Array.from(lanesMap.values()).sort((a, b) => {
    const [aGroup, aIndex] = laneOrder(a.agent);
    const [bGroup, bIndex] = laneOrder(b.agent);
    return aGroup - bGroup || aIndex - bIndex;
  });
}

export function useGenerate(): UseGenerateReturn {
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [admission, setAdmission] = useState<AdmissionState>("idle");
  const [admissionError, setAdmissionError] = useState<string | null>(null);
  const admissionResolveRef = useRef<((outcome: AdmissionOutcome) => void) | null>(null);
  const operationRef = useRef<OperationHandle | null>(null);
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [results, setResults] = useState<ExamQuestion[]>([]);
  const [displayResults, setDisplayResults] = useState<GeneratedQuestion[]>([]);
  const [evidence, setEvidence] = useState<RunEvidenceState | null>(null);
  const evidenceRef = useRef<RunEvidenceState | null>(null);
  const [llmCalls, setLlmCalls] = useState<LlmCallEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [generationLogId, setGenerationLogId] = useState<string | null>(null);
  const [subQuestionTotal, setSubQuestionTotal] = useState<number | null>(null);
  const [resultsCompletion, setResultsCompletion] = useState<ResultsCompletion | null>(null);
  const [terminalEvidence, setTerminalEvidence] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const nextFinalIndexRef = useRef(0);
  const trailByQuestionRef = useRef(new Map<string, VerificationTrailEntry[]>());
  const figurePolicyTrailByQuestionRef = useRef(
    new Map<string, FigurePolicyTrailEntry[]>(),
  );
  const referenceExampleEntriesByQuestionRef = useRef(
    new Map<string, ReferenceExampleEntryShape[]>(),
  );
  const terminalQuestionKeysRef = useRef(new Set<string>());
  const expectedQuestionTotalRef = useRef<number | null>(null);
  const paramsRef = useRef<GenerateParams | null>(null);

  const agentLanes = useMemo(() => buildAgentLanes(llmCalls), [llmCalls]);

  const settleAdmission = useCallback((outcome: AdmissionOutcome) => {
    if (!admissionResolveRef.current) return;
    setAdmission(outcome.outcome);
    setAdmissionError(outcome.outcome === "rejected" ? outcome.reason : null);
    admissionResolveRef.current(outcome);
    admissionResolveRef.current = null;
  }, []);

  const endOperation = useCallback((outcome: OperationOutcome) => {
    operationRef.current?.end(outcome);
    operationRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      admissionResolveRef.current?.({ outcome: "rejected", reason: "aborted" });
      admissionResolveRef.current = null;
      endOperation("aborted");
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [endOperation]);

  const reset = useCallback(() => {
    admissionResolveRef.current?.({ outcome: "rejected", reason: "reset" });
    admissionResolveRef.current = null;
    endOperation("aborted");
    setAdmission("idle");
    setAdmissionError(null);
    controllerRef.current?.abort();
    controllerRef.current = null;
    setProgressLines([]);
    setResults([]);
    setDisplayResults([]);
    setEvidence(null);
    evidenceRef.current = null;
    setLlmCalls([]);
    setErrorMessage(null);
    setStartedAt(null);
    setFinishedAt(null);
    setGenerationLogId(null);
    setSubQuestionTotal(null);
    setResultsCompletion(null);
    setTerminalEvidence(false);
    nextFinalIndexRef.current = 0;
    trailByQuestionRef.current.clear();
    figurePolicyTrailByQuestionRef.current.clear();
    referenceExampleEntriesByQuestionRef.current.clear();
    terminalQuestionKeysRef.current.clear();
    expectedQuestionTotalRef.current = null;
    setStatus("idle");
  }, [endOperation]);

  const restoreResults = useCallback((snapshot: ResultsWorkspaceSnapshot): boolean => {
    if (controllerRef.current !== null) return false;
    const hydrated = importResultsWorkspace(snapshot);
    if (!hydrated) return false;
    setResults(hydrated.results);
    setDisplayResults(hydrated.displayResults);
    setProgressLines(hydrated.progressLines);
    setErrorMessage(hydrated.errorMessage);
    setStartedAt(hydrated.startedAt);
    setFinishedAt(hydrated.finishedAt);
    setGenerationLogId(hydrated.runId ?? null);
    setSubQuestionTotal(hydrated.subQuestionTotal);
    // A legacy result envelope may say "settled" without carrying the
    // authoritative question-terminal evidence introduced for recovery. Do
    // not turn that missing proof into a success claim on restore.
    const restoredCompletion = hydrated.completion === "settled" && hydrated.terminalEvidence !== true
      ? "unknown"
      : hydrated.completion;
    setResultsCompletion(restoredCompletion);
    setTerminalEvidence(hydrated.terminalEvidence === true);
    setStatus(restoredCompletion === "error" ? "error" : "idle");
    setAdmission("idle");
    setAdmissionError(null);
    setLlmCalls([]);
    return true;
  }, []);

  const generate = useCallback((params: GenerateParams): Promise<AdmissionOutcome> => {
    admissionResolveRef.current?.({ outcome: "rejected", reason: "superseded" });
    endOperation("superseded");
    const admissionPromise = new Promise<AdmissionOutcome>((resolve) => {
      admissionResolveRef.current = resolve;
    });
    paramsRef.current = params;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    const streamContext = {
      startedAt: Date.now(),
      messageCount: 0,
      lastEventType: "none",
    };

    const token = useAuthStore.getState().token;

    // Create a fresh decoder for this connection
    const decoder = createGenerationStreamDecoder();

    setStatus("generating");
    setAdmission("submitting");
    setAdmissionError(null);
    setProgressLines([]);
    setResults([]);
    setDisplayResults([]);
    setEvidence(null);
    evidenceRef.current = null;
    setLlmCalls([]);
    setErrorMessage(null);
    setStartedAt(streamContext.startedAt);
    setFinishedAt(null);
    setGenerationLogId(null);
    setSubQuestionTotal(null);
    setResultsCompletion(null);
    setTerminalEvidence(false);
    nextFinalIndexRef.current = 0;
    trailByQuestionRef.current.clear();
    figurePolicyTrailByQuestionRef.current.clear();
    referenceExampleEntriesByQuestionRef.current.clear();
    terminalQuestionKeysRef.current.clear();
    expectedQuestionTotalRef.current = typeof params.count === "number" ? params.count : null;

    // ---------------------------------------------------------------------------
    // V2 event handler — routes decoded v2 events to evidence + llmCalls
    // ---------------------------------------------------------------------------
    function handleV2Event(name: string, context: Record<string, unknown>, payload: unknown) {
      const p = payload as Record<string, unknown>;

      switch (name) {
        case "started": {
          setStatus("generating");
          settleAdmission({ outcome: "admitted" });
          // Build evidence from decoder's manifest
          if (decoder.run) {
            const initial = createRunEvidence(decoder.run);
            evidenceRef.current = initial;
            setEvidence(initial);
          }
          break;
        }
        case "llm_request": {
          const agent = (p.agent as string | undefined) ?? purposeToAgent((p.purpose as string | undefined) ?? "");
          setLlmCalls((prev) => [...prev, {
            type: "request",
            purpose: (p.purpose as string | undefined) ?? (p.agent as string | undefined) ?? "",
            agent,
            model: (p.model as string) ?? "",
            messages: (p.messages as unknown[]) ?? [],
            params: p.params,
          }]);
          break;
        }
        case "llm_thinking": {
          const agent = (p.agent as string | undefined) ?? purposeToAgent((p.purpose as string | undefined) ?? "");
          const purpose = (p.purpose as string | undefined) ?? (p.agent as string | undefined) ?? "";
          const text = (p.text as string) ?? "";
          setLlmCalls((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.type === "thinking" && last.purpose === purpose) {
              return [...prev.slice(0, -1), { ...last, text: last.text + text }];
            }
            return [...prev, { type: "thinking", purpose, agent, text }];
          });
          break;
        }
        case "llm_content": {
          const agent = (p.agent as string | undefined) ?? purposeToAgent((p.purpose as string | undefined) ?? "");
          const purpose = (p.purpose as string | undefined) ?? (p.agent as string | undefined) ?? "";
          const text = (p.text as string) ?? "";
          setLlmCalls((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.type === "content" && last.purpose === purpose) {
              return [...prev.slice(0, -1), { ...last, text: last.text + text }];
            }
            return [...prev, { type: "content", purpose, agent, text }];
          });
          break;
        }
        case "llm_response": {
          const agent = (p.agent as string | undefined) ?? purposeToAgent((p.purpose as string | undefined) ?? "");
          setLlmCalls((prev) => [...prev, {
            type: "response",
            purpose: (p.purpose as string | undefined) ?? (p.agent as string | undefined) ?? "",
            agent,
            model: (p.model as string) ?? "",
            usage: p.usage,
          }]);
          break;
        }
        case "stage": {
          setLlmCalls((prev) => [...prev, {
            type: "stage",
            agent: (p.agent as string) ?? "",
            stage: (p.stage as string) ?? "",
            status: (p.status as "start" | "end" | "error") ?? "start",
            ts: (p.ts as number) ?? 0,
            retry: p.retry as number | undefined,
            message: p.message as string | undefined,
          }]);
          break;
        }
        case "plan": {
          const total = p.sub_question_total;
          if (typeof total === "number") setSubQuestionTotal(total);
          break;
        }
        case "trail": {
          const parsed = p as unknown as VerificationTrailEntry | FigurePolicyTrailEntry | ReferenceExampleEntryShape;
          if (!parsed.question_id) break;
          if (parsed.code === "verification_trail") {
            const previous = trailByQuestionRef.current.get(parsed.question_id) ?? [];
            const trail = [...previous, parsed as VerificationTrailEntry];
            trailByQuestionRef.current.set(parsed.question_id, trail);
          } else if (parsed.code === "figure_policy") {
            const previous = figurePolicyTrailByQuestionRef.current.get(parsed.question_id) ?? [];
            const fpt = [...previous, parsed as FigurePolicyTrailEntry];
            figurePolicyTrailByQuestionRef.current.set(parsed.question_id, fpt);
          } else if (parsed.code === "reference_example") {
            const previous = referenceExampleEntriesByQuestionRef.current.get(parsed.question_id) ?? [];
            const entries = [...previous, parsed as ReferenceExampleEntryShape];
            referenceExampleEntriesByQuestionRef.current.set(parsed.question_id, entries);
          }
          break;
        }
        case "question_update":
        case "result":
        case "question_terminal":
        case "pipeline": {
          // Route to evidence reducer
          const prev = evidenceRef.current;
          if (!prev) break;
          const next = applyV2Event(prev, { kind: "v2", event: { name, context, payload } });
          evidenceRef.current = next;
          setEvidence(next);
          // Track question_terminal for terminalEvidence settlement
          if (name === "question_terminal") {
            const questionId = typeof context.question_id === "string" ? context.question_id : null;
            if (questionId !== null) terminalQuestionKeysRef.current.add(questionId);
          }
          // In v2 mode, also update displayResults and results from evidence
          if (name === "result" || name === "question_update") {
            // Derive displayResults from evidence manifest order
            const newDisplay: GeneratedQuestion[] = [];
            for (const entry of next.order) {
              const qev = next.questions[entry];
              if (qev && qev.content.question) {
                const qid = qev.questionId;
                const laneKey = qid;
                const refEntries = referenceExampleEntriesByQuestionRef.current.get(laneKey);
                newDisplay.push({
                  index: qev.index,
                  question: qev.content.question,
                  phase: (qev.content.phase ?? "draft") as DraftPhase,
                  isFinal: qev.content.receipt === "final",
                  stableId: qev.questionId,
                  contentRevision: typeof qev.content.revision === "number" && qev.content.revision > 0
                    ? qev.content.revision
                    : null,
                  trail: trailByQuestionRef.current.get(laneKey) ?? [],
                  figurePolicyTrail: figurePolicyTrailByQuestionRef.current.get(laneKey) ?? [],
                  referenceExampleRecord: refEntries
                    ? { disabled: false, entries: refEntries }
                    : { disabled: paramsRef.current?.disable_reference_fewshot === true, entries: [] },
                });
              }
            }
            setDisplayResults(newDisplay);
            // results = unique finals in manifest order
            const newResults = next.order
              .map((qid) => next.questions[qid])
              .filter((qev) => qev?.content.receipt === "final" && qev.content.question)
              .map((qev) => qev.content.question!);
            setResults(newResults);
          }
          break;
        }
        case "error": {
          const errPayload = payload as { message?: string; code?: string } | string | null;
          let msg = "Unknown error";
          if (typeof errPayload === "string") msg = errPayload;
          else if (errPayload && typeof errPayload === "object" && typeof errPayload.message === "string") {
            msg = errPayload.message;
          }
          setErrorMessage(msg);
          setStatus("error");
          setResultsCompletion("error");
          setTerminalEvidence(false);
          setFinishedAt(Date.now());
          endOperation("failed");
          break;
        }
        case "done": {
          // Apply done to close the evidence run
          const prev = evidenceRef.current;
          if (prev) {
            const closed = applyV2Event(prev, { kind: "v2", event: { name, context, payload } });
            evidenceRef.current = closed;
            setEvidence(closed);
          }
          {
            const expected = expectedQuestionTotalRef.current;
            const hasTerminalEvidence = expected === null
              ? terminalQuestionKeysRef.current.size > 0
              : expected > 0 && terminalQuestionKeysRef.current.size >= expected;
            setTerminalEvidence(hasTerminalEvidence);
            setResultsCompletion(hasTerminalEvidence ? "settled" : "unknown");
          }
          setStatus("idle");
          setFinishedAt(Date.now());
          endOperation("completed");
          controller.abort();
          controllerRef.current = null;
          break;
        }
        default:
          break;
      }
    }

    // ---------------------------------------------------------------------------
    // Legacy event handler — existing switch statement logic unchanged
    // ---------------------------------------------------------------------------
    function handleLegacyEvent(eventName: string, data: string) {
      switch (eventName) {
        case "started":
          setStatus("generating");
          settleAdmission({ outcome: "admitted" });
          {
            const payload = parseStartedEventData(data);
            if (payload) setGenerationLogId(payload.generation_log_id);
          }
          break;
        case "progress":
          setProgressLines((prev) => [...prev, data]);
          break;
        case "llm_request": {
          try {
            const d = JSON.parse(data) as { purpose: string; agent?: string; model: string; messages: unknown[]; params?: unknown };
            const agent = d.agent ?? purposeToAgent(d.purpose);
            setLlmCalls((prev) => [...prev, { type: "request", purpose: d.purpose, agent, model: d.model, messages: d.messages, params: d.params }]);
          } catch { /* ignore */ }
          break;
        }
        case "llm_thinking": {
          try {
            const d = JSON.parse(data) as { purpose: string; agent?: string; text: string };
            const agent = d.agent ?? purposeToAgent(d.purpose);
            setLlmCalls((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.type === "thinking" && last.purpose === d.purpose) {
                return [...prev.slice(0, -1), { ...last, text: last.text + d.text }];
              }
              return [...prev, { type: "thinking", purpose: d.purpose, agent, text: d.text }];
            });
          } catch { /* ignore */ }
          break;
        }
        case "llm_content": {
          try {
            const d = JSON.parse(data) as { purpose: string; agent?: string; text: string };
            const agent = d.agent ?? purposeToAgent(d.purpose);
            setLlmCalls((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.type === "content" && last.purpose === d.purpose) {
                return [...prev.slice(0, -1), { ...last, text: last.text + d.text }];
              }
              return [...prev, { type: "content", purpose: d.purpose, agent, text: d.text }];
            });
          } catch { /* ignore */ }
          break;
        }
        case "llm_response": {
          try {
            const d = JSON.parse(data) as { purpose: string; agent?: string; model: string; usage?: unknown };
            const agent = d.agent ?? purposeToAgent(d.purpose);
            setLlmCalls((prev) => [...prev, { type: "response", purpose: d.purpose, agent, model: d.model, usage: d.usage }]);
          } catch { /* ignore */ }
          break;
        }
        case "stage": {
          try {
            const d = JSON.parse(data) as { agent: string; stage: string; status: "start" | "end" | "error"; ts: number; retry?: number; message?: string };
            setLlmCalls((prev) => [...prev, { type: "stage", agent: d.agent, stage: d.stage, status: d.status, ts: d.ts, retry: d.retry, message: d.message }]);
          } catch { /* ignore */ }
          break;
        }
        case "plan": {
          try {
            const d = JSON.parse(data) as { sub_question_total: number };
            setSubQuestionTotal(d.sub_question_total);
          } catch { /* ignore */ }
          break;
        }
        case "pipeline":
          // pipeline-level events (pipeline_start, question_start/end, pipeline_end) — no UI action needed beyond stage events
          break;
        case "question_update": {
          try {
            const parsed = JSON.parse(data) as {
              index: number;
              phase: DraftPhase;
              question: ExamQuestion;
              stable_id?: string;
              content_revision?: number | null;
            };
            const laneKey = questionKey(parsed.question, parsed.index);
            const draftEntries = referenceExampleEntriesByQuestionRef.current.get(laneKey) ?? [];
            const draftRefRecord: ReferenceExampleRecordShape = draftEntries.length > 0
              ? { disabled: false, entries: draftEntries }
              : { disabled: paramsRef.current?.disable_reference_fewshot === true, entries: [] };
            setDisplayResults((prev) => upsertDisplayResult(prev, {
              index: parsed.index,
              question: parsed.question,
              phase: parsed.phase,
              isFinal: false,
              stableId: parsed.stable_id ?? questionKey(parsed.question, parsed.index),
              contentRevision: typeof parsed.content_revision === "number" && parsed.content_revision > 0
                ? parsed.content_revision
                : null,
              trail: trailByQuestionRef.current.get(laneKey) ?? [],
              figurePolicyTrail: figurePolicyTrailByQuestionRef.current.get(laneKey) ?? [],
              referenceExampleRecord: draftRefRecord,
            }));
          } catch { /* ignore malformed draft updates */ }
          break;
        }
        case "trail": {
          try {
            const parsed = JSON.parse(data) as
              | VerificationTrailEntry
              | FigurePolicyTrailEntry
              | ReferenceExampleEntryShape;
            if (!parsed.question_id) break;
            if (parsed.code === "verification_trail") {
              const previous = trailByQuestionRef.current.get(parsed.question_id) ?? [];
              const trail = [...previous, parsed as VerificationTrailEntry];
              trailByQuestionRef.current.set(parsed.question_id, trail);
              setDisplayResults((prev) => prev.map((item) => (
                questionKey(item.question, item.index) === parsed.question_id
                  ? { ...item, trail }
                  : item
              )));
            } else if (parsed.code === "figure_policy") {
              const previous = figurePolicyTrailByQuestionRef.current.get(parsed.question_id) ?? [];
              const figurePolicyTrail = [...previous, parsed as FigurePolicyTrailEntry];
              figurePolicyTrailByQuestionRef.current.set(parsed.question_id, figurePolicyTrail);
              setDisplayResults((prev) => prev.map((item) => (
                questionKey(item.question, item.index) === parsed.question_id
                  ? { ...item, figurePolicyTrail }
                  : item
              )));
            } else if (parsed.code === "reference_example") {
              const previous = referenceExampleEntriesByQuestionRef.current.get(parsed.question_id) ?? [];
              const entries = [...previous, parsed as ReferenceExampleEntryShape];
              referenceExampleEntriesByQuestionRef.current.set(parsed.question_id, entries);
              setDisplayResults((prev) => prev.map((item) => (
                questionKey(item.question, item.index) === parsed.question_id
                  ? { ...item, referenceExampleRecord: { disabled: false, entries } }
                  : item
              )));
            }
          } catch { /* ignore malformed trail events */ }
          break;
        }
        case "question_terminal":
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const ctx = parsed.context && typeof parsed.context === "object"
              ? parsed.context as Record<string, unknown>
              : null;
            const questionId = typeof parsed.question_id === "string"
              ? parsed.question_id
              : typeof ctx?.question_id === "string"
                ? ctx.question_id
                : Number.isInteger(parsed.index) ? `index-${parsed.index}` : null;
            if (questionId !== null) terminalQuestionKeysRef.current.add(questionId);
          } catch { /* legacy streams may not send JSON terminal envelopes */ }
          break;
        case "result":
          try {
            const raw = JSON.parse(data) as ExamQuestion & {
              stable_id?: string;
              question_id?: string;
              content_revision?: number | null;
              question?: ExamQuestion;
            };
            const parsed = raw.question !== undefined && typeof raw.question === "object" && raw.question !== null
              ? raw.question
              : raw;
            const index = nextFinalIndexRef.current;
            nextFinalIndexRef.current += 1;
            setResults((prev) => [...prev, parsed]);
            const laneKey = questionKey(parsed, index);
            const refEntries = referenceExampleEntriesByQuestionRef.current.get(laneKey);
            setDisplayResults((prev) => upsertDisplayResult(prev, {
              index,
              question: parsed,
              phase: "verified",
              isFinal: true,
              stableId: raw.stable_id ?? raw.question_id ?? questionKey(parsed, index),
              contentRevision: typeof raw.content_revision === "number" && raw.content_revision > 0
                ? raw.content_revision
                : null,
              trail: trailByQuestionRef.current.get(laneKey) ?? [],
              figurePolicyTrail: figurePolicyTrailByQuestionRef.current.get(laneKey) ?? [],
              referenceExampleRecord: refEntries
                ? { disabled: false, entries: refEntries }
                : { disabled: paramsRef.current?.disable_reference_fewshot === true, entries: [] },
            }));
          } catch {
            setStatus("error");
          }
          break;
        case "error":
          setErrorMessage(parseErrorEventData(data ?? ""));
          setStatus("error");
          setResultsCompletion("error");
          setTerminalEvidence(false);
          setFinishedAt(Date.now());
          endOperation("failed");
          break;
        case "done": {
          const expected = expectedQuestionTotalRef.current;
          const hasTerminalEvidence = expected === null
            ? terminalQuestionKeysRef.current.size > 0
            : expected > 0 && terminalQuestionKeysRef.current.size >= expected;
          setTerminalEvidence(hasTerminalEvidence);
          setResultsCompletion(hasTerminalEvidence ? "settled" : "unknown");
          setStatus("idle");
          setFinishedAt(Date.now());
          endOperation("completed");
          controller.abort();
          controllerRef.current = null;
          break;
        }
      }
    }

    operationRef.current = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    fetchEventSource("/api/generate", {
      method: "POST",
      body: JSON.stringify({ ...params, stream_version: 2 }),
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      openWhenHidden: true,
      async onopen(res) {
        if (controllerRef.current !== controller) return;
        if (!res.ok) {
          if (res.status === 401) {
            // Classify as credential expiry — recovery snapshot is preserved
            // so the teacher can restore after re-authenticating (#776).
            const authState = useAuthStore.getState();
            const userId = authState.user?.id ?? null;
            if (userId !== null) {
              saveSignoutReason("session_expired", userId);
            }
            const currentPath =
              typeof window !== "undefined" ? window.location.pathname : null;
            if (currentPath !== null) {
              saveReturnDestination(currentPath);
            }
            authState.logout();
            const msg = "Session expired — please sign in again";
            setErrorMessage(msg);
            setStatus("error");
            setResultsCompletion("error");
            setTerminalEvidence(false);
            setFinishedAt(Date.now());
            settleAdmission({ outcome: "rejected", reason: msg });
            endOperation("failed");
            throw new FatalStreamError(msg);
          }
          let msg = `Stream open failed: HTTP ${res.status}`;
          try {
            const body = await res.json() as unknown;
            if (
              body !== null &&
              typeof body === "object" &&
              "detail" in body
            ) {
              msg = formatHttpErrorDetail((body as Record<string, unknown>).detail) ?? msg;
            }
          } catch {
            // non-JSON or unreadable body — keep the generic message
          }
          if (controllerRef.current !== controller) return;
          setErrorMessage(msg);
          setStatus("error");
          setResultsCompletion("error");
          setTerminalEvidence(false);
          setFinishedAt(Date.now());
          settleAdmission({ outcome: "rejected", reason: msg });
          endOperation("failed");
          throw new FatalStreamError(msg);
        }
      },
      onmessage(ev) {
        if (controllerRef.current !== controller) return;
        streamContext.messageCount += 1;
        streamContext.lastEventType = ev.event || "none";

        // Decode through the connection's decoder
        const decoded = decoder.decode(ev.event ?? "", ev.data ?? "");
        for (const d of decoded) {
          if (d.kind === "mode" && d.mode === "unsupported") {
            // Unknown protocol or bad manifest: abort, set error
            const reasonKey = d.reason === "unknown_protocol"
              ? "stream.unsupported_unknown_protocol"
              : d.reason === "invalid_manifest"
                ? "stream.unsupported_invalid_manifest"
                : "stream.unsupported_missing_started";
            const msg = MESSAGES["zh-TW"][reasonKey] ?? reasonKey;
            setErrorMessage(msg);
            setStatus("error");
            setResultsCompletion("error");
            setTerminalEvidence(false);
            setFinishedAt(Date.now());
            settleAdmission({ outcome: "rejected", reason: reasonKey });
            endOperation("failed");
            controller.abort();
            controllerRef.current = null;
            return;
          }

          if (d.kind === "v2") {
            // V2 mode: route decoded event
            handleV2Event(d.event.name, d.event.context, d.event.payload);
          } else if (d.kind === "legacy") {
            // Legacy mode: use existing switch handler
            handleLegacyEvent(d.name, d.data);
          } else if (d.kind === "held") {
            // Event held pending started: immediately process as legacy so existing
            // tests (which don't send started first) continue to work.
            handleLegacyEvent(ev.event ?? "", ev.data ?? "");
          }
          // ignore: no action
        }
      },
      onerror(err) {
        if (controllerRef.current !== controller) return;
        const message = err instanceof Error ? err.message : String(err);
        setErrorMessage(message);
        setStatus("error");
        setResultsCompletion("error");
        setTerminalEvidence(false);
        setFinishedAt(Date.now());
        settleAdmission({ outcome: "rejected", reason: message });
        endOperation("failed");
        throw err instanceof Error ? err : new FatalStreamError(String(err));
      },
    }).catch((err: unknown) => {
      if (controllerRef.current !== controller) return;
      if (err instanceof Error && err.name !== "AbortError" && isSentryEnabled()) {
        Sentry.captureException(err, {
          tags: {
            source: "fetchEventSource",
            last_event_type: streamContext.lastEventType,
            navigator_online: String(navigator.onLine),
          },
          contexts: {
            stream: {
              elapsed_ms: Date.now() - streamContext.startedAt,
              message_count: streamContext.messageCount,
            },
          },
        });
      }
      // Stream terminated (abort or fatal error). State already updated.
    });
    return admissionPromise;
  }, [endOperation, settleAdmission]);

  return {
    admission,
    admissionError,
    restoreResults,
    status,
    progressLines,
    results,
    displayResults,
    evidence,
    llmCalls,
    agentLanes,
    errorMessage,
    startedAt,
    finishedAt,
    generationLogId,
    subQuestionTotal,
    resultsCompletion,
    terminalEvidence,
    generate,
    reset,
  };
}
