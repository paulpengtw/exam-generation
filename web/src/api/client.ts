import { useAuthStore } from "../store/authStore";
import {
  type FigurePolicyTrailEntry,
  type GenerateParams,
  type VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { ResolveResponse } from "./generated/contract";
import { saveSignoutReason } from "../lib/signoutReason";
import { saveReturnDestination } from "../lib/returnDestination";
import { isResolverFieldErrorLike, type ResolverFieldErrorLike } from "../lib/resolverErrorMessages";
import type { GenerationSlotReference } from "../lib/generationEvidence";

export interface MagicLinkResponse {
  message: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface SchemaEntry {
  value: string;
  instruction: string;
  parent?: string;
  admitted_by?: Record<string, string[]>;
}

export interface LearningPerformanceEntry extends SchemaEntry {
  科目: string;
}

export interface Schemas {
  學習階段: string;
  grades: number[];
  情境: SchemaEntry[];
  情境子類別?: SchemaEntry[];
  題型種類: SchemaEntry[];
  題型: SchemaEntry[];
  認知歷程?: SchemaEntry[];
  內容領域?: SchemaEntry[];
  數學思考: SchemaEntry[];
  核心素養?: SchemaEntry[];
  reporting_scale?: SchemaEntry[];
  科學能力?: SchemaEntry[];
  question_style?: SchemaEntry[];
  題目內容類型?: SchemaEntry[];
  科目?: SchemaEntry[];
  學習表現?: LearningPerformanceEntry[];
  學習內容?: LearningPerformanceEntry[];
  內容領域_mapping?: Record<string, string[]>;
  digital_only_question_types?: string[];
  figure_kinds?: string[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  detail: string;
  code?: string;
  /** Field-addressed resolver errors parsed from an array-valued `detail` (#835). */
  errors?: ResolverFieldErrorLike[];

  constructor(status: number, detail: string, code?: string, errors?: ResolverFieldErrorLike[]) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.errors = errors;
  }
}

/** Parse an array-valued `detail` into field-addressed resolver errors, if it looks like one. */
function parseResolverFieldErrors(detail: unknown): ResolverFieldErrorLike[] | undefined {
  if (!Array.isArray(detail) || detail.length === 0) return undefined;
  return detail.every(isResolverFieldErrorLike) ? detail : undefined;
}

async function extractError(
  res: Response,
): Promise<{ detail: string; code?: string; errors?: ResolverFieldErrorLike[] }> {
  try {
    const body = await res.json() as unknown;
    if (body && typeof body === "object") {
      const payload = body as Record<string, unknown>;
      const detail = typeof payload.message === "string"
        ? payload.message
        : typeof payload.detail === "string"
          ? payload.detail
          : undefined;
      const code = typeof payload.error === "string" ? payload.error : undefined;
      if (detail) return { detail, code };
      // #835: keep the string path above unchanged; additionally surface a
      // non-string (array) `detail` as parsed field errors instead of
      // discarding it, so callers can format it readably.
      const errors = parseResolverFieldErrors(payload.detail);
      if (errors) return { detail: `Request failed with status ${res.status}`, errors };
    }
  } catch {
    // ignore
  }
  return { detail: `Request failed with status ${res.status}` };
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = useAuthStore.getState().token;
  const headers = new Headers(options.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    if (res.status === 401) {
      // Classify as credential expiry (not explicit logout) — recovery snapshot
      // is preserved so the teacher can restore after re-authenticating (#776).
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
    }
    const error = await extractError(res);
    throw new ApiError(res.status, error.detail, error.code, error.errors);
  }
  return res;
}

export async function sendMagicLink(email: string): Promise<MagicLinkResponse> {
  const res = await apiFetch("/auth/magic-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return (await res.json()) as MagicLinkResponse;
}

export async function verifyMagicLink(token: string, email: string): Promise<TokenResponse> {
  const params = new URLSearchParams({ token, email });
  const res = await apiFetch(`/auth/verify?${params.toString()}`);
  return (await res.json()) as TokenResponse;
}

export async function getMe(): Promise<User> {
  const res = await apiFetch("/auth/me");
  return (await res.json()) as User;
}

export async function getSchemas(subject = "math", grade?: number): Promise<Schemas> {
  const params = new URLSearchParams({ subject });
  if (grade != null) params.set("grade", String(grade));
  const res = await apiFetch(`/api/schemas?${params.toString()}`);
  return (await res.json()) as Schemas;
}

export interface PlanCoreQuestionsRequest {
  topic: string;
  subject?: string;
  subject_filter?: string[];
  grade?: number;
}

export interface PlanCoreQuestionsResponse {
  candidates: string[];
}

export async function planCoreQuestions(
  req: PlanCoreQuestionsRequest,
  signal?: AbortSignal,
): Promise<PlanCoreQuestionsResponse> {
  const res = await apiFetch("/api/plan-core-questions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  return (await res.json()) as PlanCoreQuestionsResponse;
}

export interface PromptPreview {
  index: number;
  /** Zero-based subquestion index (0..N-1), matching the SSE stream convention.
   * The frontend adds +1 to display as 第1小題..第N小題. */
  subquestion_index?: number;
  system_prompt: string;
  user_prompt: string;
}

export interface PreviewGenerateResponse {
  prompts: PromptPreview[];
}

export async function previewGenerate(params: GenerateParams): Promise<PreviewGenerateResponse> {
  const res = await apiFetch("/api/generate/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = await res.json() as unknown;
  if (
    !body ||
    typeof body !== "object" ||
    !("prompts" in body) ||
    !Array.isArray(body.prompts) ||
    !body.prompts.every((prompt) => (
      prompt &&
      typeof prompt === "object" &&
      "index" in prompt &&
      Number.isInteger(prompt.index) &&
      prompt.index >= 0 &&
      (
        !("subquestion_index" in prompt) ||
        (
          Number.isInteger(prompt.subquestion_index) &&
          (prompt.subquestion_index as number) >= 0
        )
      ) &&
      "system_prompt" in prompt &&
      typeof prompt.system_prompt === "string" &&
      "user_prompt" in prompt &&
      typeof prompt.user_prompt === "string"
    ))
  ) {
    throw new Error("Malformed prompt preview response");
  }
  return { prompts: body.prompts as PromptPreview[] };
}

export async function resolveGenerate(
  payload: Record<string, unknown>,
  redraws: Record<string, number> = {},
): Promise<ResolveResponse> {
  const res = await apiFetch("/api/generate/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, redraws }),
  });
  const body = await res.json() as unknown;
  if (
    !body ||
    typeof body !== "object" ||
    !("payload" in body) ||
    !body.payload ||
    typeof body.payload !== "object" ||
    Array.isArray(body.payload) ||
    !("drawn" in body) ||
    !Array.isArray(body.drawn) ||
    !body.drawn.every((path) => typeof path === "string") ||
    !("cleared" in body) ||
    !Array.isArray(body.cleared) ||
    !body.cleared.every((path) => typeof path === "string")
  ) {
    throw new Error("Malformed resolve response");
  }
  return {
    payload: body.payload as Record<string, unknown>,
    drawn: body.drawn as string[],
    cleared: body.cleared as string[],
  };
}

export interface AvailableModels {
  allowed: string[];
  effort?: Record<string, string[]>;
  defaults: { plan: string; execute: string; verify: string; correct: string; effort_plan?: string; effort_execute?: string; effort_verify?: string; effort_correct?: string };
}

export async function getAvailableModels(): Promise<AvailableModels> {
  const res = await apiFetch("/api/models");
  return (await res.json()) as AvailableModels;
}

export type HistoryRecordStatus = "completed" | "failed" | "aborted";

export interface HistoryListItem {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  status: HistoryRecordStatus;
  error: string | null;
  preview: string;
  verified: boolean;
  figure_policy_trail: FigurePolicyTrailEntry[] | null;
}

export interface HistoryListResponse {
  total: number;
  items: HistoryListItem[];
}

/** Typed terminal delivery summary returned by GET /api/history/{id}. */
export interface HistoryTerminalDelivery {
  delivery_status: "complete" | "partial" | "none" | "unknown" | null;
  missing: GenerationSlotReference[];
  termination_reason: "normal" | "failed" | "cancelled" | null;
}

export interface HistoryDetail {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  status: HistoryRecordStatus;
  error: string | null;
  generation_log_id: string | null;
  params_json: Record<string, unknown>;
  question_json: Record<string, unknown> | null;
  verification_trail: VerificationTrailEntry[] | null;
  figure_policy_trail: FigurePolicyTrailEntry[] | null;
  reference_example_record: { disabled?: boolean; entries: unknown[] } | null;
  /**
   * Terminal delivery summary computed at save time (issue #939).
   * Null for old records and modification records.
   * Old records fall back to `delivery_status: "complete"` and `missing: []`.
   */
  terminal_delivery: HistoryTerminalDelivery | null;
}

export interface ListHistoryOpts {
  limit?: number;
  offset?: number;
  subject?: string;
  signal?: AbortSignal;
}

export async function listHistory(
  opts: ListHistoryOpts = {},
): Promise<HistoryListResponse> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  if (opts.subject) params.set("subject", opts.subject);
  const suffix = params.toString();
  const res = await apiFetch(
    suffix ? `/api/history?${suffix}` : "/api/history",
    { signal: opts.signal },
  );
  return (await res.json()) as HistoryListResponse;
}

export async function getHistoryDetail(id: string): Promise<HistoryDetail> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}`);
  return (await res.json()) as HistoryDetail;
}

/** Summary row from `GET /api/runs` (all of the owner's runs, newest first). */
export interface RunListItem {
  run_id: string;
  status: string;
  subject: string | null;
  started_at: string | null;
  completed_at: string | null;
  queue_position: number | null;
  cancel_requested: boolean;
}

/**
 * List all of the authenticated owner's runs (`GET /api/runs`), newest first.
 * Each row includes `queue_position` (non-null only when status === "queued")
 * and `cancel_requested`.
 */
export async function listRuns(opts: { signal?: AbortSignal } = {}): Promise<RunListItem[]> {
  const res = await apiFetch("/api/runs", { signal: opts.signal });
  return (await res.json()) as RunListItem[];
}

/**
 * Read the persisted state of a detached 生成執行 (`GET /api/runs/{id}`).
 * Owner-only: any other caller (or an unknown id) gets `ApiError` status 404.
 * The body is returned unparsed; `parseRunSnapshot` validates its shape.
 */
export async function getRun(runId: string): Promise<unknown> {
  const res = await apiFetch(`/api/runs/${encodeURIComponent(runId)}`);
  return (await res.json()) as unknown;
}

/**
 * Request cancellation of a 生成執行 (`POST /api/runs/{id}/cancel`).
 * Owner-only; a non-owner or unknown id gets `ApiError` status 404.
 * Idempotent: succeeds even if the run is already ended or already cancelled.
 */
export async function cancelRun(runId: string): Promise<void> {
  await apiFetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export async function downloadHistoryJson(id: string, signal?: AbortSignal): Promise<Blob> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}/download`, { signal });
  return await res.blob();
}

export interface ModificationSegmentRequest {
  field_path: string;
  start: number;
  end: number;
  quoted_text: string;
}

export interface ModificationAnnotationRequest {
  segments: ModificationSegmentRequest[];
  修改指示: string;
}

export interface ModificationBatchRequest {
  annotations: ModificationAnnotationRequest[];
}

export interface ModificationBatchResponse {
  run_id: string;
  status: string;
}

export async function submitModificationBatch(
  recordId: string,
  batch: ModificationBatchRequest,
): Promise<ModificationBatchResponse> {
  const res = await apiFetch(
    `/api/generation-records/${encodeURIComponent(recordId)}/modifications`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(batch),
    },
  );
  return (await res.json()) as ModificationBatchResponse;
}
