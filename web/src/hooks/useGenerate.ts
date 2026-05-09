import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { useAuthStore } from "../store/authStore";

export type GenerateStatus = "idle" | "generating" | "error";

export interface GenerateParams {
  grade?: number;
  style?: string[];
  context?: string[];
  set_type?: string;
  q_type?: string[];
  count?: number;
  skip_verify?: boolean;
  seed?: number;
}

export interface LearningContentItem {
  編碼: string;
  說明: string;
}

export interface ExamQuestion {
  id?: string;
  情境: string[];
  題型種類: string;
  題型: string;
  數學思考: string[];
  學習內容: LearningContentItem[];
  題目: string[];
  正確解題分析: string[];
  圖片?: string | null;
  chart_spec?: unknown;
  verification?: unknown;
  metadata?: unknown;
  image_base64?: string;
}

export interface UseGenerateReturn {
  status: GenerateStatus;
  progressLines: string[];
  results: ExamQuestion[];
  generate: (params: GenerateParams) => void;
  reset: () => void;
}

class FatalStreamError extends Error {}

function buildQueryString(params: GenerateParams): string {
  const qs = new URLSearchParams();
  if (params.grade !== undefined) qs.append("grade", String(params.grade));
  if (params.set_type !== undefined) qs.append("set_type", params.set_type);
  if (params.count !== undefined) qs.append("count", String(params.count));
  if (params.skip_verify !== undefined) qs.append("skip_verify", String(params.skip_verify));
  if (params.seed !== undefined) qs.append("seed", String(params.seed));
  for (const v of params.style ?? []) qs.append("style", v);
  for (const v of params.context ?? []) qs.append("context", v);
  for (const v of params.q_type ?? []) qs.append("q_type", v);
  return qs.toString();
}

export function useGenerate(): UseGenerateReturn {
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [results, setResults] = useState<ExamQuestion[]>([]);
  const controllerRef = useRef<AbortController | null>(null);

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
    setStatus("idle");
  }, []);

  const generate = useCallback((params: GenerateParams) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    const token = useAuthStore.getState().token;
    const qs = buildQueryString(params);
    const url = qs ? `/api/generate?${qs}` : "/api/generate";

    setStatus("generating");
    setProgressLines([]);
    setResults([]);

    fetchEventSource(url, {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      openWhenHidden: true,
      async onopen(res) {
        if (!res.ok) {
          throw new FatalStreamError(`Stream open failed with status ${res.status}`);
        }
      },
      onmessage(ev) {
        switch (ev.event) {
          case "progress":
            setProgressLines((prev) => [...prev, ev.data]);
            break;
          case "result":
            try {
              const parsed = JSON.parse(ev.data) as ExamQuestion;
              setResults((prev) => [...prev, parsed]);
            } catch {
              setStatus("error");
            }
            break;
          case "error":
            setStatus("error");
            break;
          case "done":
            setStatus("idle");
            controller.abort();
            controllerRef.current = null;
            break;
        }
      },
      onerror(err) {
        setStatus("error");
        throw err instanceof Error ? err : new FatalStreamError(String(err));
      },
    }).catch(() => {
      // Stream terminated (abort or fatal error). State already updated.
    });
  }, []);

  return { status, progressLines, results, generate, reset };
}
