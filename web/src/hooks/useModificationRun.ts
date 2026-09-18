import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

import {
  submitModificationBatch,
  type ModificationBatchRequest,
} from "../api/client";
import type { AdmissionState, ExamQuestion } from "./useGenerate";
import { useAuthStore } from "../store/authStore";
import { useWorkspaceStore, type OperationHandle, type OperationOutcome } from "../lib/workspace/workspaceStore";

export type ModificationRunStatus = "idle" | "running" | "completed" | "error";
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

export interface UseModificationRunReturn {
  status: ModificationRunStatus;
  admission: AdmissionState;
  admissionError: string | null;
  stageEvents: ModificationStageEvent[];
  result: ModificationRunResult | null;
  error: unknown | null;
  start: (batch: ModificationBatchRequest) => Promise<void>;
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

export function useModificationRun(
  recordId?: string,
  initialResult: ModificationRunResult | null = null,
): UseModificationRunReturn {
  const [status, setStatus] = useState<ModificationRunStatus>(
    initialResult === null ? "idle" : "completed",
  );
  const [admission, setAdmission] = useState<AdmissionState>("idle");
  const [admissionError, setAdmissionError] = useState<string | null>(null);
  const operationRef = useRef<OperationHandle | null>(null);
  const [stageEvents, setStageEvents] = useState<ModificationStageEvent[]>([]);
  const [result, setResult] = useState<ModificationRunResult | null>(initialResult);
  const [error, setError] = useState<unknown | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const runSequenceRef = useRef(0);
  const sourceRecordIdRef = useRef(recordId);
  const activeRecordIdRef = useRef(initialResult?.record_id ?? recordId);

  useEffect(() => {
    if (sourceRecordIdRef.current === recordId) return;
    sourceRecordIdRef.current = recordId;
    activeRecordIdRef.current = recordId;
  }, [recordId]);

  const endOperation = useCallback((outcome: OperationOutcome) => {
    operationRef.current?.end(outcome);
    operationRef.current = null;
  }, []);

  useEffect(() => () => {
    endOperation("aborted");
    runSequenceRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, [endOperation]);

  const start = useCallback(async (batch: ModificationBatchRequest) => {
    const activeRecordId = activeRecordIdRef.current;
    if (!activeRecordId) return;

    endOperation("superseded");
    operationRef.current = useWorkspaceStore.getState().beginOperation("modification", "history.modification");

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const sequence = ++runSequenceRef.current;
    let terminalResult: ModificationRunResult | null = null;
    let streamFailed = false;
    let admitted = false;

    setStatus("running");
    setAdmission("submitting");
    setAdmissionError(null);
    setStageEvents([]);
    setError(null);

    const isCurrent = () => runSequenceRef.current === sequence;

    try {
      const admission = await submitModificationBatch(activeRecordId, batch);
      if (!isCurrent() || controller.signal.aborted) return;
      if (!admission.run_id) {
        throw new Error("Modification admission did not return a run id");
      }

      admitted = true;
      setAdmission("admitted");

      const token = useAuthStore.getState().token;
      await fetchEventSource(
        `/api/generation-records/${encodeURIComponent(activeRecordId)}/modifications/${encodeURIComponent(admission.run_id)}/stream`,
        {
          signal: controller.signal,
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          openWhenHidden: true,
          async onopen(response) {
            if (response.ok) return;
            let message = `Modification stream failed: HTTP ${response.status}`;
            try {
              const payload = await response.json() as unknown;
              if (
                payload !== null &&
                typeof payload === "object" &&
                typeof (payload as Record<string, unknown>).detail === "string"
              ) {
                message = (payload as Record<string, string>).detail;
              }
            } catch {
              // Keep the status-based message when the body is not JSON.
            }
            throw new Error(message);
          },
          onmessage(event) {
            if (!isCurrent()) return;
            if (event.event === "stage") {
              const stage = parseStage(event.data);
              if (stage) setStageEvents((previous) => [...previous, stage]);
              return;
            }
            if (event.event === "result") {
              terminalResult = parseResult(event.data);
              return;
            }
            if (event.event === "error") {
              streamFailed = true;
              setError(parseError(event.data));
              setStatus("error");
              endOperation("failed");
              return;
            }
            if (event.event === "done") {
              const doneResult = parseResult(event.data) ?? terminalResult;
              if (streamFailed) return;
              if (doneResult === null) {
                setError(new Error("Modification stream ended without a result"));
                setStatus("error");
                endOperation("failed");
                return;
              }
              terminalResult = doneResult;
              if (doneResult.record_id !== null) {
                activeRecordIdRef.current = doneResult.record_id;
              }
              setResult(doneResult);
              setStatus("completed");
              endOperation("completed");
              controller.abort();
              controllerRef.current = null;
            }
          },
          onerror(streamError) {
            if (isCurrent() && !controller.signal.aborted) {
              streamFailed = true;
              setError(streamError);
              setStatus("error");
              endOperation("failed");
            }
            throw streamError instanceof Error
              ? streamError
              : new Error(String(streamError));
          },
        },
      );
    } catch (streamError) {
      if (isCurrent() && !controller.signal.aborted) {
        setError(streamError);
        setStatus("error");
        if (!admitted) {
          setAdmission("rejected");
          setAdmissionError(streamError instanceof Error ? streamError.message : String(streamError));
        }
        endOperation("failed");
      }
    }
  }, [endOperation]);

  return { status, admission, admissionError, stageEvents, result, error, start };
}
