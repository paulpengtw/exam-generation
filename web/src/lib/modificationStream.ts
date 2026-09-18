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

function parseError(raw: string): Error {
  const parsed = parseJson(raw);
  if (parsed !== null && typeof parsed === "object") {
    const message = (parsed as Record<string, unknown>).message;
    if (typeof message === "string" && message.length > 0) {
      return new Error(message);
    }
  }
  return new Error(raw || "Modification stream failed");
}

export type ModificationStreamEvent =
  | { kind: "stage"; event: ModificationStageEvent }
  | { kind: "result"; result: ModificationRunResult }
  | { kind: "error"; error: Error }
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
    case "error":
      return { kind: "error", error: parseError(rawData) };
    case "done":
      return { kind: "done", result: parseResult(rawData) };
    default:
      return null;
  }
}
