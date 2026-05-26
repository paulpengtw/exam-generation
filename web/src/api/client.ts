import { useAuthStore } from "../store/authStore";

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
}

export interface Schemas {
  學習階段: string;
  grades: number[];
  情境: SchemaEntry[];
  題型種類: SchemaEntry[];
  題型: SchemaEntry[];
  數學思考: SchemaEntry[];
  question_style?: SchemaEntry[];
  科目?: SchemaEntry[];
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

export async function getSchemas(subject = "math"): Promise<Schemas> {
  const res = await apiFetch(`/api/schemas?subject=${encodeURIComponent(subject)}`);
  return (await res.json()) as Schemas;
}

export interface PlanCoreQuestionsRequest {
  topic: string;
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
