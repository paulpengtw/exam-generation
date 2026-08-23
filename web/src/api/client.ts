import { useAuthStore } from "../store/authStore";
import { buildQueryString, type GenerateParams } from "../hooks/useGenerate";

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
  數學思考: SchemaEntry[];
  科學能力?: SchemaEntry[];
  question_style?: SchemaEntry[];
  題目內容類型?: SchemaEntry[];
  科目?: SchemaEntry[];
  學習表現?: LearningPerformanceEntry[];
  學習內容?: LearningPerformanceEntry[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function extractDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // ignore
  }
  return `Request failed with status ${res.status}`;
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
      useAuthStore.getState().logout();
    }
    throw new ApiError(res.status, await extractDetail(res));
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
): Promise<PlanCoreQuestionsResponse> {
  const res = await apiFetch("/api/plan-core-questions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return (await res.json()) as PlanCoreQuestionsResponse;
}

export interface PromptPreview {
  index: number;
  subquestion_index?: number;
  system_prompt: string;
  user_prompt: string;
}

export interface PreviewGenerateResponse {
  prompts: PromptPreview[];
}

export async function previewGenerate(params: GenerateParams): Promise<PreviewGenerateResponse> {
  const res = await apiFetch(`/api/generate/preview?${buildQueryString(params)}`);
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
}

export interface HistoryListResponse {
  total: number;
  items: HistoryListItem[];
}

export interface HistoryDetail {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  status: HistoryRecordStatus;
  error: string | null;
  params_json: Record<string, unknown>;
  question_json: Record<string, unknown> | null;
}

export interface ListHistoryOpts {
  limit?: number;
  offset?: number;
  subject?: string;
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
  );
  return (await res.json()) as HistoryListResponse;
}

export async function getHistoryDetail(id: string): Promise<HistoryDetail> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}`);
  return (await res.json()) as HistoryDetail;
}

export async function downloadHistoryJson(id: string): Promise<Blob> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}/download`);
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

export async function submitModificationBatch(
  recordId: string,
  batch: ModificationBatchRequest,
): Promise<Response> {
  return apiFetch(
    `/api/generation-records/${encodeURIComponent(recordId)}/modifications`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(batch),
    },
  );
}
