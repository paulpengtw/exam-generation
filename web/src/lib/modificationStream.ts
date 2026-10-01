import type { ExamQuestion } from "../hooks/useGenerate";
import type { ModificationEvidence } from "./runEvidence";

export type ModificationStageName = "modification" | "verify" | "correct";

export interface ModificationStageEvent {
  type: "stage";
  agent: string;
  stage: ModificationStageName;
  step: string;
  status: "start" | "end" | "error";
  ts: number;
  retry?: number;
  message?: string;
}

export interface ModificationRunResult {
  record_id: string | null;
  question: ExamQuestion;
  ripple_report: string[];
  verified: boolean;
  verification: unknown;
  failure_details: string | null;
}

export function projectModificationEvidence(
  steps: readonly ModificationStageEvent[],
): ModificationEvidence {
  return { profile: "modification", steps };
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function parseStage(raw: string): ModificationStageEvent | null {
  const parsed = parseJson(raw);
  if (parsed === null || typeof parsed !== "object") return null;
  const data = parsed as Record<string, unknown>;
  const stage = data.stage;
  const status = data.status;
  if (
    (stage !== "modification" && stage !== "verify" && stage !== "correct") ||
    (status !== "start" && status !== "end" && status !== "error") ||
    typeof data.agent !== "string" ||
    typeof data.step !== "string" ||
    typeof data.ts !== "number"
  ) {
    return null;
  }
  return {
    type: "stage",
    agent: data.agent,
    stage,
    step: data.step,
    status,
    ts: data.ts,
    ...(typeof data.retry === "number" ? { retry: data.retry } : {}),
    ...(typeof data.message === "string" ? { message: data.message } : {}),
  };
}

function parseResult(raw: string): ModificationRunResult | null {
  const parsed = parseJson(raw);
  if (parsed === null || typeof parsed !== "object") return null;
  const data = parsed as Record<string, unknown>;
  if (data.question === null || typeof data.question !== "object") return null;
  return {
    record_id: typeof data.record_id === "string" ? data.record_id : null,
    question: data.question as ExamQuestion,
    ripple_report: Array.isArray(data.ripple_report)
      ? data.ripple_report.filter((path): path is string => typeof path === "string")
      : [],
    verified: data.verified === true,
    verification: data.verification ?? null,
    failure_details: typeof data.failure_details === "string"
      ? data.failure_details
      : null,
  };
}

const _TAXONOMY_CODES_MOD = new Set([
  "auth_config",
  "quota_billing_exhausted",
  "rate_limited",
  "overloaded",
  "timeout",
  "connection",
  "context_length",
  "content_filtered",
  "malformed_response",
  "unknown",
]);

function parseError(raw: string): { error: Error; failureClass: string | null } {
  const parsed = parseJson(raw);
  let errorMsg: string | null = null;
  let failureClass: string | null = null;
  if (parsed !== null && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    const message = obj.message;
    if (typeof message === "string" && message.length > 0) {
      errorMsg = message;
    }
    const fc = obj.failure_class;
    if (typeof fc === "string" && _TAXONOMY_CODES_MOD.has(fc)) {
      failureClass = fc;
    }
  }
  return {
    error: new Error(errorMsg ?? (raw || "Modification stream failed")),
    failureClass,
  };
}

export type ModificationStreamEvent =
  | { kind: "stage"; event: ModificationStageEvent }
  | { kind: "result"; result: ModificationRunResult }
  | { kind: "error"; error: Error; failureClass: string | null }
  | { kind: "done"; result: ModificationRunResult | null };

export function decodeModificationEvent(
  eventName: string,
  rawData: string,
): ModificationStreamEvent | null {
  switch (eventName) {
    case "stage": {
      const event = parseStage(rawData);
      return event === null ? null : { kind: "stage", event };
    }
    case "result": {
      const result = parseResult(rawData);
      return result === null ? null : { kind: "result", result };
    }
    case "error": {
      const { error, failureClass } = parseError(rawData);
      return { kind: "error", error, failureClass };
    }
    case "done":
      return { kind: "done", result: parseResult(rawData) };
    default:
      return null;
  }
}
