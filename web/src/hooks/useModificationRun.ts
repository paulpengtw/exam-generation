import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

import {
  submitModificationBatch,
  type ModificationBatchRequest,
} from "../api/client";
import type { AdmissionState } from "./useGenerate";
import { useAuthStore } from "../store/authStore";
import { useWorkspaceStore, type OperationHandle, type OperationOutcome } from "../lib/workspace/workspaceStore";
import { decodeModificationEvent, type ModificationStageEvent, type ModificationRunResult } from "../lib/modificationStream";

export type { ModificationStageName, ModificationStageEvent, ModificationRunResult } from "../lib/modificationStream";

export type ModificationRunStatus = "idle" | "running" | "completed" | "error";

export interface UseModificationRunReturn {
  status: ModificationRunStatus;
  admission: AdmissionState;
  admissionError: string | null;
  stageEvents: ModificationStageEvent[];
  result: ModificationRunResult | null;
  error: unknown | null;
  start: (batch: ModificationBatchRequest) => Promise<void>;
}

export function useModificationRun(recordId?: string): UseModificationRunReturn {
  const [status, setStatus] = useState<ModificationRunStatus>("idle");
  const [admission, setAdmission] = useState<AdmissionState>("idle");
  const [admissionError, setAdmissionError] = useState<string | null>(null);
  const operationRef = useRef<OperationHandle | null>(null);
  const [stageEvents, setStageEvents] = useState<ModificationStageEvent[]>([]);
  const [result, setResult] = useState<ModificationRunResult | null>(null);
  const [error, setError] = useState<unknown | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const runSequenceRef = useRef(0);
  const sourceRecordIdRef = useRef(recordId);
  const activeRecordIdRef = useRef(recordId);

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
            const decoded = decodeModificationEvent(event.event, event.data);
            if (decoded === null) {
              // A malformed result clears any earlier buffered result, as before.
              if (event.event === "result") terminalResult = null;
              return;
            }
            if (decoded.kind === "stage") {
              setStageEvents((previous) => [...previous, decoded.event]);
              return;
            }
            if (decoded.kind === "result") {
              terminalResult = decoded.result;
              return;
            }
            if (decoded.kind === "error") {
              streamFailed = true;
              setError(decoded.error);
              setStatus("error");
              endOperation("failed");
              return;
            }
            if (decoded.kind === "done") {
              const doneResult = decoded.result ?? terminalResult;
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
