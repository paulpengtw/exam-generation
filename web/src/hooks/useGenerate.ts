import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Sentry from "@sentry/react";

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import { isSentryEnabled } from "../sentry";
import { saveSignoutReason } from "../lib/signoutReason";
import { saveReturnDestination } from "../lib/returnDestination";
import type { GenerateParams } from "../api/generated/contract";
import { MESSAGES } from "../i18n/messages";
import {
  applyRunSnapshot,
  deriveDisplay,
  evidenceFromAccepted,
  isTerminalRunStatus,
  parseAcceptedRun,
  parseRunSnapshot,
  snapshotEnded,
  stageEventsFromSnapshot,
  DETACHED_RUN_PROTOCOL_VERSION,
  type RunSnapshot,
} from "../lib/runSnapshot";
import { closeRun, selectEndedCount, type RunEvidenceState } from "../lib/generationEvidence";
import { ApiError, getRun } from "../api/client";
import {
  formatResolverFieldErrors,
  isResolverFieldErrorLike,
} from "../lib/resolverErrorMessages";

import { useReleaseStore } from "../lib/release/releaseStore";
import { useWorkspaceStore, type OperationHandle, type OperationOutcome } from "../lib/workspace/workspaceStore";
import { importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import type { ResultsCompletion, ResultsWorkspaceSnapshot } from "../lib/workspace/adapters/types";

export type { GenerateParams };

export type AdmissionState = "idle" | "submitting" | "admitted" | "rejected";
export type AdmissionOutcome =
  | { outcome: "admitted"; runId?: string }
  | { outcome: "rejected"; reason: string };

/** Result of reopening a run by id (`?run=<id>`). */
export type ResumeOutcome =
  | { outcome: "resumed" }
  | { outcome: "not_found" }
  | { outcome: "failed"; reason: string };

export type GenerateStatus = "idle" | "generating" | "error";

export interface LearningContentItem {
  編碼: string;
  說明: string;
}

export interface RubricEntry {
  /** Opaque scoring-level text: new records use fixed 2 / 1 / 0; legacy 0..N and 2/1/0/0X both render. */
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
  科目?: string[];
  科學能力?: string[];
  核心素養?: string[];
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
  核心素養?: string[];
  學習表現?: LearningContentItem[];
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
  content_revision?: number | null;
}

export interface VerificationTrailInitialEntry {
  code: "verification_trail";
  kind: "initial";
  question_id: string;
  timestamp: string;
  snapshot: Record<string, unknown>;
  content_revision?: number | null;
}

export interface VerificationTrailRejectionReason {
  code: string;
  path: string;
  message: string;
}

export interface VerificationTrailCorrectionEntry {
  code: "verification_trail";
  kind: "correction";
  question_id: string;
  retry_index: number;
  model: string;
  timestamp: string;
  snapshot: Record<string, unknown>;
  outcome?: "accepted" | "rejected";
  reason?: VerificationTrailRejectionReason;
  content_revision?: number | null;
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
  content_revision?: number | null;
}

export interface FigurePolicyCollisionEntry {
  code: "figure_policy";
  kind: "collision";
  question_id: string;
  left: string;
  right: string;
  effective_figure_kind: string;
  timestamp: string;
  content_revision?: number | null;
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
  content_revision?: number | null;
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
  content_revision?: number | null;
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
  content_revision?: number | null;
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
  /**
   * True when the original batch position could not be resolved.
   * Set for legacy-adapter items that have no consistent index↔id evidence.
   * UI should show "原題序未知" instead of "第 N 題" for these items.
   */
  positionUnknown?: boolean;
}

interface LlmIdentity {
  runId?: string;
  operationId?: string;
  callId?: string;
  channel?: "thinking" | "content";
  retryOfCallId?: string;
  supersedesOperationId?: string;
}

export type LlmCallEvent =
  | ({ type: "request"; purpose: string; agent: string; model: string; messages: unknown[]; params?: unknown } & LlmIdentity)
  | ({ type: "thinking"; purpose: string; agent: string; text: string } & LlmIdentity)
  | ({ type: "content"; purpose: string; agent: string; text: string } & LlmIdentity)
  | ({ type: "response"; purpose: string; agent: string; model: string; usage?: unknown } & LlmIdentity)
  | ({ type: "failure"; purpose: string; agent: string; model: string; errorType?: string } & LlmIdentity)
  | ({ type: "stage"; agent: string; stage: string; status: "start" | "end" | "error"; ts: number; retry?: number; message?: string } & LlmIdentity);

export type StageEvent = Extract<LlmCallEvent, { type: "stage" }>;

export type AgentStatus = "idle" | "running" | "done" | "error";

export interface AgentLane {
  agent: string;
  operationId?: string;
  status: AgentStatus;
  currentStage: string | null;
  streamingThinking: string;
  streamingContent: string;
  stageHistory: Array<{ stage: string; startedAt: number; endedAt?: number; retry?: number }>;
  errorMessage?: string;
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
    fact_check: "fact_checker",
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
  /** Id of the detached run being shown (accepted or resumed); null when none. */
  runId: string | null;
  subQuestionTotal: number | null;
  admission: AdmissionState;
  admissionError: string | null;
  /** Optional for callers that do not render recovery status (legacy mocks). */
  resultsCompletion?: ResultsCompletion | null;
  terminalEvidence?: boolean;
  generate: (params: GenerateParams) => Promise<AdmissionOutcome>;
  /** Reopen a detached run by id and keep polling it. Never cancels anything. */
  resume: (runId: string) => Promise<ResumeOutcome>;
  restoreResults: (snapshot: ResultsWorkspaceSnapshot) => boolean;
  reset: () => void;
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
  qs.append("stream_version", String(DETACHED_RUN_PROTOCOL_VERSION));
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

  const getOrCreate = (agent: string, operationId?: string): AgentLane => {
    const key = operationId ? `${agent}:${operationId}` : agent;
    if (!lanesMap.has(key)) {
      lanesMap.set(key, {
        agent,
        operationId,
        status: "idle",
        currentStage: null,
        streamingThinking: "",
        streamingContent: "",
        stageHistory: [],
      });
    }
    return lanesMap.get(key)!;
  };

  for (const ev of events) {
    if (ev.type === "stage") {
      const lane = getOrCreate(ev.agent, ev.operationId);
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
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose), ev.operationId);
      lane.status = "running";
      lane.streamingThinking = "";
      lane.streamingContent = "";
    } else if (ev.type === "thinking") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose), ev.operationId);
      lane.streamingThinking += ev.text;
    } else if (ev.type === "content") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose), ev.operationId);
      lane.streamingContent += ev.text;
    } else if (ev.type === "response") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose), ev.operationId);
      if (lane.status === "running" && !lane.currentStage) {
        lane.status = "done";
      }
    } else if (ev.type === "failure") {
      const lane = getOrCreate(ev.agent ?? purposeToAgent(ev.purpose), ev.operationId);
      lane.status = "error";
      lane.errorMessage = ev.errorType;
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

/** Poll cadence for a detached run (issue #908): brisk while watched, lazy when hidden. */
export const RUN_POLL_VISIBLE_MS = 3_000;
export const RUN_POLL_HIDDEN_MS = 15_000;
/** Polls that must agree the run status is terminal before questions without a 終止原因 are given up on. */
const STATUS_SETTLE_POLLS = 2;

function currentPollInterval(): number {
  return typeof document !== "undefined" && document.visibilityState === "hidden"
    ? RUN_POLL_HIDDEN_MS
    : RUN_POLL_VISIBLE_MS;
}

function localMessage(key: string): string {
  const lang = useLangStore.getState().lang;
  return MESSAGES[lang][key] ?? MESSAGES["zh-TW"][key] ?? key;
}

/** One local polling session. Ending it only stops timers; nothing is sent to the server. */
interface ActiveRun {
  runId: string | null;
  timer: ReturnType<typeof setTimeout> | null;
  lastPollAt: number;
  stageKey: string;
  terminalStatusPolls: number;
  /** True for a run reopened by id: the start time comes from the server. */
  resumed: boolean;
  detachVisibility: (() => void) | null;
}

type PollResult =
  | { kind: "stale" }
  | { kind: "applied"; ended: boolean }
  | { kind: "not_found" }
  | { kind: "fatal"; message: string }
  | { kind: "transient" };

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
  const [runId, setRunId] = useState<string | null>(null);
  const [subQuestionTotal, setSubQuestionTotal] = useState<number | null>(null);
  const [resultsCompletion, setResultsCompletion] = useState<ResultsCompletion | null>(null);
  const [terminalEvidence, setTerminalEvidence] = useState(false);
  const activeRef = useRef<ActiveRun | null>(null);
  /** Run whose state is currently on screen, even after its polling ended. */
  const shownRunRef = useRef<string | null>(null);

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

  /** Stop watching locally. The run itself keeps going on the server. */
  const stopWatching = useCallback(() => {
    const run = activeRef.current;
    if (run === null) return;
    if (run.timer !== null) clearTimeout(run.timer);
    run.timer = null;
    run.detachVisibility?.();
    run.detachVisibility = null;
    activeRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      admissionResolveRef.current?.({ outcome: "rejected", reason: "aborted" });
      admissionResolveRef.current = null;
      endOperation("aborted");
      // Leaving the page must not cancel the run (issue #908): only local polling stops.
      stopWatching();
    };
  }, [endOperation, stopWatching]);

  const clearRunState = useCallback(() => {
    setProgressLines([]);
    setLlmCalls([]);
    setEvidence(null);
    evidenceRef.current = null;
    setResults([]);
    setDisplayResults([]);
    setErrorMessage(null);
    setStartedAt(null);
    setFinishedAt(null);
    setGenerationLogId(null);
    setRunId(null);
    shownRunRef.current = null;
    setSubQuestionTotal(null);
    setResultsCompletion(null);
    setTerminalEvidence(false);
  }, []);

  const reset = useCallback(() => {
    admissionResolveRef.current?.({ outcome: "rejected", reason: "reset" });
    admissionResolveRef.current = null;
    endOperation("aborted");
    setAdmission("idle");
    setAdmissionError(null);
    stopWatching();
    clearRunState();
    setStatus("idle");
  }, [clearRunState, endOperation, stopWatching]);

  const restoreResults = useCallback((snapshot: ResultsWorkspaceSnapshot): boolean => {
    if (activeRef.current !== null) return false;
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

  /** Fold a polled snapshot into state. Repeating the same snapshot changes nothing. */
  const applySnapshot = useCallback((snapshot: RunSnapshot, run: ActiveRun): { ended: boolean } => {
    const previous = evidenceRef.current;
    let next = applyRunSnapshot(previous, snapshot);
    if (next !== previous) {
      evidenceRef.current = next;
      setEvidence(next);
      const derived = deriveDisplay(next);
      setDisplayResults(derived.displayResults);
      setResults(derived.results);
    }

    const stages = stageEventsFromSnapshot(snapshot);
    const stageKey = JSON.stringify(stages);
    if (stageKey !== run.stageKey) {
      run.stageKey = stageKey;
      setLlmCalls(stages);
    }

    if (run.resumed) {
      run.resumed = false;
      const started = snapshot.started_at !== null ? Date.parse(snapshot.started_at) : Number.NaN;
      setStartedAt(Number.isNaN(started) ? Date.now() : started);
      setGenerationLogId(snapshot.run_id);
      setRunId(snapshot.run_id);
      shownRunRef.current = snapshot.run_id;
    }

    let ended = snapshotEnded(snapshot);
    if (!ended && isTerminalRunStatus(snapshot.status)) {
      run.terminalStatusPolls += 1;
      if (run.terminalStatusPolls >= STATUS_SETTLE_POLLS) {
        // The run says it is over but some question never got a 終止原因:
        // stop watching and let the evidence say "unknown" for it.
        ended = true;
        if (!next.closed) {
          next = closeRun(next);
          evidenceRef.current = next;
          setEvidence(next);
        }
      }
    } else {
      run.terminalStatusPolls = 0;
    }
    if (!ended) return { ended: false };

    const completedAt = snapshot.completed_at !== null ? Date.parse(snapshot.completed_at) : Number.NaN;
    setFinishedAt(Number.isNaN(completedAt) ? Date.now() : completedAt);
    if (snapshot.status === "failed") {
      setErrorMessage(snapshot.error ?? localMessage("generate.run_failed"));
      setStatus("error");
      setResultsCompletion("error");
      setTerminalEvidence(false);
      endOperation("failed");
    } else {
      const settled = next.total > 0 && selectEndedCount(next) >= next.total;
      setTerminalEvidence(settled);
      setResultsCompletion(settled ? "settled" : "unknown");
      setStatus("idle");
      endOperation("completed");
    }
    return { ended: true };
  }, [endOperation]);

  /** One `GET /api/runs/{id}`. Only reads; never cancels. */
  const pollOnce = useCallback(async (run: ActiveRun): Promise<PollResult> => {
    if (run.runId === null) return { kind: "stale" };
    run.lastPollAt = Date.now();
    try {
      const raw = await getRun(run.runId);
      if (activeRef.current !== run) return { kind: "stale" };
      const snapshot = parseRunSnapshot(raw);
      if (snapshot === null) return { kind: "fatal", message: localMessage("generate.run_invalid_response") };
      return { kind: "applied", ended: applySnapshot(snapshot, run).ended };
    } catch (err) {
      if (activeRef.current !== run) return { kind: "stale" };
      if (err instanceof ApiError) {
        if (err.status === 404) return { kind: "not_found" };
        if (err.status === 401) return { kind: "fatal", message: "Session expired — please sign in again" };
        // Rate limiting and server trouble pass; the run itself is unaffected.
        if (err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429) {
          return { kind: "fatal", message: err.detail };
        }
      }
      return { kind: "transient" };
    }
  }, [applySnapshot]);

  /** Fail the shown run locally (the server-side run is untouched). */
  const failWatching = useCallback((message: string) => {
    stopWatching();
    setErrorMessage(message);
    setStatus("error");
    setFinishedAt(Date.now());
    endOperation("failed");
  }, [endOperation, stopWatching]);

  /** Poll on a timer while the page is alive: ~3 s visible, ~15 s hidden. */
  const startPolling = useCallback((run: ActiveRun) => {
    const schedule = () => {
      if (activeRef.current !== run) return;
      if (run.timer !== null) clearTimeout(run.timer);
      const wait = Math.max(0, currentPollInterval() - (Date.now() - run.lastPollAt));
      run.timer = setTimeout(step, wait);
    };
    const step = async () => {
      run.timer = null;
      const result = await pollOnce(run);
      if (activeRef.current !== run) return;
      if (result.kind === "applied" && result.ended) {
        stopWatching();
        return;
      }
      if (result.kind === "fatal") {
        failWatching(result.message);
        return;
      }
      if (result.kind === "not_found") {
        failWatching(localMessage("generate.run_not_found"));
        return;
      }
      schedule();
    };
    const onVisibilityChange = () => {
      if (activeRef.current === run && run.timer !== null) schedule();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
      run.detachVisibility = () => document.removeEventListener("visibilitychange", onVisibilityChange);
    }
    run.lastPollAt = Date.now();
    schedule();
  }, [failWatching, pollOnce, stopWatching]);

  const newRun = useCallback((id: string | null, resumed: boolean): ActiveRun => ({
    runId: id,
    timer: null,
    lastPollAt: Date.now(),
    stageKey: "[]",
    terminalStatusPolls: 0,
    resumed,
    detachVisibility: null,
  }), []);

  const generate = useCallback(async (params: GenerateParams): Promise<AdmissionOutcome> => {
    if (activeRef.current !== null) {
      return { outcome: "rejected", reason: "generation already in progress" };
    }
    const admissionPromise = new Promise<AdmissionOutcome>((resolve) => {
      admissionResolveRef.current = resolve;
    });
    const run = newRun(null, false);
    activeRef.current = run;
    const submittedAt = Date.now();
    const token = useAuthStore.getState().token;

    setStatus("generating");
    setAdmission("submitting");
    setAdmissionError(null);
    setProgressLines([]);
    // Previous results, displayResults and evidence are cleared only once the
    // server accepts the run — so previous output survives pre-acceptance
    // failures (426 / 503 / preflight failure).  See issue #771.
    setLlmCalls([]);
    setErrorMessage(null);
    setStartedAt(submittedAt);
    setFinishedAt(null);
    setGenerationLogId(null);
    setRunId(null);
    shownRunRef.current = null;
    setSubQuestionTotal(null);

    // A rejected submission is reported to Sentry (when enabled) as before the
    // detached-run transport; only the message is sent, never request content.
    const rejectSubmission = (message: string, cause?: Error) => {
      if (isSentryEnabled()) {
        Sentry.captureException(cause ?? new Error(message), {
          tags: { source: "generateSubmit", navigator_online: String(navigator.onLine) },
          contexts: { submit: { elapsed_ms: Date.now() - submittedAt } },
        });
      }
      if (activeRef.current === run) activeRef.current = null;
      setErrorMessage(message);
      setStatus("error");
      setFinishedAt(Date.now());
      settleAdmission({ outcome: "rejected", reason: message });
      endOperation("failed");
    };

    // Preflight: ensure we have a current release status before submission.
    // Trigger a network check for the initial "checking" state and retry an
    // "unavailable" result. When the background poller already set a
    // definitive status, use it directly — this keeps generate() synchronous
    // in the common current/update-required/paused cases and avoids a
    // microtask deferral that would break tests using a synchronous act().
    const releaseStatus = useReleaseStore.getState().status;
    if (releaseStatus === "checking" || releaseStatus === "unavailable") {
      await useReleaseStore.getState().checkNow();
    }
    if (activeRef.current !== run) return admissionPromise;
    const preflightStatus = useReleaseStore.getState().status;
    if (preflightStatus === "update-required" || preflightStatus === "paused" || preflightStatus === "unavailable") {
      const msgKey =
        preflightStatus === "update-required"
          ? "generate.preflight_update_required"
          : preflightStatus === "paused"
            ? "generate.preflight_paused"
            : "generate.preflight_unavailable";
      const msg = MESSAGES["zh-TW"][msgKey] ?? msgKey;
      setAdmission("idle");
      setAdmissionError(msg);
      activeRef.current = null;
      setErrorMessage(msg);
      setStatus("error");
      setFinishedAt(Date.now());
      settleAdmission({ outcome: "rejected", reason: msg });
      return admissionPromise;
    }
    operationRef.current = useWorkspaceStore.getState().beginOperation("generation", "generate.results");

    let response: Response;
    try {
      response = await fetch("/api/generate", {
        method: "POST",
        body: JSON.stringify({ ...params, stream_version: DETACHED_RUN_PROTOCOL_VERSION }),
        headers: {
          "Content-Type": "application/json",
          "X-Frontend-Build-ID": __BUILD_ID__,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch (err) {
      if (activeRef.current !== run) return admissionPromise;
      const message = err instanceof Error ? err.message : String(err);
      rejectSubmission(message, err instanceof Error ? err : undefined);
      return admissionPromise;
    }
    if (activeRef.current !== run) return admissionPromise;

    if (!response.ok) {
      if (response.status === 401) {
        // Classify as credential expiry — recovery snapshot is preserved
        // so the teacher can restore after re-authenticating (#776).
        const authState = useAuthStore.getState();
        const userId = authState.user?.id ?? null;
        if (userId !== null) saveSignoutReason("session_expired", userId);
        const currentPath = typeof window !== "undefined" ? window.location.pathname : null;
        if (currentPath !== null) saveReturnDestination(currentPath);
        authState.logout();
        rejectSubmission("Session expired — please sign in again");
        return admissionPromise;
      }
      let message = `Submit failed: HTTP ${response.status}`;
      try {
        const body = await response.json() as unknown;
        if (body !== null && typeof body === "object" && "detail" in body) {
          message = formatHttpErrorDetail((body as Record<string, unknown>).detail) ?? message;
        }
      } catch {
        // non-JSON or unreadable body — keep the generic message
      }
      if (activeRef.current !== run) return admissionPromise;
      rejectSubmission(message);
      return admissionPromise;
    }

    let accepted;
    try {
      accepted = parseAcceptedRun(await response.json() as unknown);
    } catch {
      accepted = { ok: false as const, reason: "invalid_manifest" as const };
    }
    if (activeRef.current !== run) return admissionPromise;
    if (!accepted.ok) {
      const reasonKey = accepted.reason === "unknown_protocol"
        ? "stream.unsupported_unknown_protocol"
        : "stream.unsupported_invalid_manifest";
      rejectSubmission(MESSAGES["zh-TW"][reasonKey] ?? reasonKey);
      return admissionPromise;
    }

    run.runId = accepted.run.run_id;
    const initial = evidenceFromAccepted(accepted.run);
    evidenceRef.current = initial;
    setEvidence(initial);
    setResults([]);
    setDisplayResults([]);
    setGenerationLogId(accepted.run.run_id);
    setRunId(accepted.run.run_id);
    shownRunRef.current = accepted.run.run_id;
    setResultsCompletion(null);
    setTerminalEvidence(false);
    setStatus("generating");
    settleAdmission({ outcome: "admitted", runId: accepted.run.run_id });
    startPolling(run);
    return admissionPromise;
  }, [endOperation, newRun, settleAdmission, startPolling]);

  const resume = useCallback(async (id: string): Promise<ResumeOutcome> => {
    const existing = activeRef.current;
    if (existing !== null) {
      return existing.runId === id
        ? { outcome: "resumed" }
        : { outcome: "failed", reason: "generation already in progress" };
    }
    // Already showing this run (e.g. it just ended after being submitted here).
    if (shownRunRef.current === id) return { outcome: "resumed" };
    const run = newRun(id, true);
    activeRef.current = run;
    clearRunState();
    setAdmission("idle");
    setAdmissionError(null);
    setStatus("generating");
    operationRef.current = useWorkspaceStore.getState().beginOperation("generation", "generate.results");

    const first = await pollOnce(run);
    if (activeRef.current !== run) return { outcome: "failed", reason: "aborted" };
    switch (first.kind) {
      case "not_found":
        stopWatching();
        endOperation("failed");
        clearRunState();
        setStatus("idle");
        return { outcome: "not_found" };
      case "fatal":
        failWatching(first.message);
        return { outcome: "failed", reason: first.message };
      case "applied":
        if (first.ended) {
          stopWatching();
        } else {
          startPolling(run);
        }
        return { outcome: "resumed" };
      default:
        // A first read that failed transiently is retried on the normal cadence.
        startPolling(run);
        return { outcome: "resumed" };
    }
  }, [clearRunState, endOperation, failWatching, newRun, pollOnce, startPolling, stopWatching]);

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
    runId,
    subQuestionTotal,
    resultsCompletion,
    terminalEvidence,
    generate,
    resume,
    reset,
  };
}
