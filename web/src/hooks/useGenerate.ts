import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import * as Sentry from "@sentry/react";

import { useAuthStore } from "../store/authStore";
import { isSentryEnabled } from "../sentry";
import type { GenerateParams, ResolveFieldError } from "../api/generated/contract";

export type { GenerateParams };

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
  llmCalls: LlmCallEvent[];
  agentLanes: AgentLane[];
  errorMessage: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  generationLogId: string | null;
  subQuestionTotal: number | null;
  generate: (params: GenerateParams) => void;
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

  const fieldErrors = detail.filter(
    (item): item is ResolveFieldError => (
      item !== null
      && typeof item === "object"
      && typeof (item as Record<string, unknown>).field === "string"
      && typeof (item as Record<string, unknown>).code === "string"
    ),
  );
  if (fieldErrors.length > 0) {
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
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [results, setResults] = useState<ExamQuestion[]>([]);
  const [displayResults, setDisplayResults] = useState<GeneratedQuestion[]>([]);
  const [llmCalls, setLlmCalls] = useState<LlmCallEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [generationLogId, setGenerationLogId] = useState<string | null>(null);
  const [subQuestionTotal, setSubQuestionTotal] = useState<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const nextFinalIndexRef = useRef(0);
  const trailByQuestionRef = useRef(new Map<string, VerificationTrailEntry[]>());
  const figurePolicyTrailByQuestionRef = useRef(
    new Map<string, FigurePolicyTrailEntry[]>(),
  );
  const referenceExampleEntriesByQuestionRef = useRef(
    new Map<string, ReferenceExampleEntryShape[]>(),
  );
  const paramsRef = useRef<GenerateParams | null>(null);

  const agentLanes = useMemo(() => buildAgentLanes(llmCalls), [llmCalls]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setProgressLines([]);
    setResults([]);
    setDisplayResults([]);
    setLlmCalls([]);
    setErrorMessage(null);
    setStartedAt(null);
    setFinishedAt(null);
    setGenerationLogId(null);
    setSubQuestionTotal(null);
    nextFinalIndexRef.current = 0;
    trailByQuestionRef.current.clear();
    figurePolicyTrailByQuestionRef.current.clear();
    referenceExampleEntriesByQuestionRef.current.clear();
    setStatus("idle");
  }, []);

  const generate = useCallback((params: GenerateParams) => {
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

    setStatus("generating");
    setProgressLines([]);
    setResults([]);
    setDisplayResults([]);
    setLlmCalls([]);
    setErrorMessage(null);
    setStartedAt(streamContext.startedAt);
    setFinishedAt(null);
    setGenerationLogId(null);
    setSubQuestionTotal(null);
    nextFinalIndexRef.current = 0;
    trailByQuestionRef.current.clear();
    figurePolicyTrailByQuestionRef.current.clear();
    referenceExampleEntriesByQuestionRef.current.clear();

    fetchEventSource("/api/generate", {
      method: "POST",
      body: JSON.stringify(params),
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
            useAuthStore.getState().logout();
            const msg = "Session expired — please sign in again";
            setErrorMessage(msg);
            setFinishedAt(Date.now());
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
          setFinishedAt(Date.now());
          throw new FatalStreamError(msg);
        }
      },
      onmessage(ev) {
        if (controllerRef.current !== controller) return;
        streamContext.messageCount += 1;
        streamContext.lastEventType = ev.event || "none";

        switch (ev.event) {
          case "started":
            setStatus("generating");
            {
              const payload = parseStartedEventData(ev.data);
              if (payload) setGenerationLogId(payload.generation_log_id);
            }
            break;
          case "progress":
            setProgressLines((prev) => [...prev, ev.data]);
            break;
          case "llm_request": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; agent?: string; model: string; messages: unknown[]; params?: unknown };
              const agent = d.agent ?? purposeToAgent(d.purpose);
              setLlmCalls((prev) => [...prev, { type: "request", purpose: d.purpose, agent, model: d.model, messages: d.messages, params: d.params }]);
            } catch { /* ignore */ }
            break;
          }
          case "llm_thinking": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; agent?: string; text: string };
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
              const d = JSON.parse(ev.data) as { purpose: string; agent?: string; text: string };
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
              const d = JSON.parse(ev.data) as { purpose: string; agent?: string; model: string; usage?: unknown };
              const agent = d.agent ?? purposeToAgent(d.purpose);
              setLlmCalls((prev) => [...prev, { type: "response", purpose: d.purpose, agent, model: d.model, usage: d.usage }]);
            } catch { /* ignore */ }
            break;
          }
          case "stage": {
            try {
              const d = JSON.parse(ev.data) as { agent: string; stage: string; status: "start" | "end" | "error"; ts: number; retry?: number; message?: string };
              setLlmCalls((prev) => [...prev, { type: "stage", agent: d.agent, stage: d.stage, status: d.status, ts: d.ts, retry: d.retry, message: d.message }]);
            } catch { /* ignore */ }
            break;
          }
          case "plan": {
            try {
              const d = JSON.parse(ev.data) as { sub_question_total: number };
              setSubQuestionTotal(d.sub_question_total);
            } catch { /* ignore */ }
            break;
          }
          case "pipeline":
            // pipeline-level events (pipeline_start, question_start/end, pipeline_end) — no UI action needed beyond stage events
            break;
          case "question_update": {
            try {
              const parsed = JSON.parse(ev.data) as { index: number; phase: DraftPhase; question: ExamQuestion };
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
                trail: trailByQuestionRef.current.get(laneKey) ?? [],
                figurePolicyTrail: figurePolicyTrailByQuestionRef.current.get(laneKey) ?? [],
                referenceExampleRecord: draftRefRecord,
              }));
            } catch { /* ignore malformed draft updates */ }
            break;
          }
          case "trail": {
            try {
              const parsed = JSON.parse(ev.data) as
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
          case "result":
            try {
              const parsed = JSON.parse(ev.data) as ExamQuestion;
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
            setErrorMessage(parseErrorEventData(ev.data ?? ""));
            setStatus("error");
            setFinishedAt(Date.now());
            break;
          case "done":
            setStatus("idle");
            setFinishedAt(Date.now());
            controller.abort();
            controllerRef.current = null;
            break;
        }
      },
      onerror(err) {
        if (controllerRef.current !== controller) return;
        setErrorMessage(err instanceof Error ? err.message : String(err));
        setStatus("error");
        setFinishedAt(Date.now());
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
  }, []);

  return {
    status,
    progressLines,
    results,
    displayResults,
    llmCalls,
    agentLanes,
    errorMessage,
    startedAt,
    finishedAt,
    generationLogId,
    subQuestionTotal,
    generate,
    reset,
  };
}
