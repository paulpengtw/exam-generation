import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { useAuthStore } from "../store/authStore";

export type GenerateStatus = "idle" | "queued" | "generating" | "error";

export interface GenerateParams {
  subject?: string;
  grade?: number;
  style?: string[];
  context?: string[];
  set_type?: string;
  q_type?: string[];
  count?: number;
  skip_verify?: boolean;
  seed?: number;
  image_generation_mode?: "html" | "gpt_image";
  subject_filter?: string;
}

export interface LearningContentItem {
  編碼: string;
  說明: string;
}

export interface RubricEntry {
  code: "2" | "1" | "0" | "0X";
  規準說明: string;
  學生作答實例?: string[];
}

export interface SubQuestion {
  id: string;
  序號: number;
  年級: number;
  科目: string[];
  核心素養: string[];
  學習內容: LearningContentItem[];
  學習表現: LearningContentItem[];
  出題概念: string;
  題型: string;
  題目: string;
  答案: string;
  答案解析: string;
  評分規準?: RubricEntry[];
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
  核心問題?: string;
  文本?: string;
  subquestions?: SubQuestion[];
  題目: string[];
  正確解題分析: string[];
  圖片?: string | null;
  chart_spec?: unknown;
  verification?: unknown;
  metadata?: unknown;
  image_base64?: string;
}

export type LlmCallEvent =
  | { type: "request"; purpose: string; model: string; messages: unknown[]; params?: unknown }
  | { type: "thinking"; purpose: string; text: string }
  | { type: "content"; purpose: string; text: string }
  | { type: "response"; purpose: string; model: string; usage?: unknown };

export interface UseGenerateReturn {
  status: GenerateStatus;
  jobsAhead: number;
  progressLines: string[];
  results: ExamQuestion[];
  llmCalls: LlmCallEvent[];
  errorMessage: string | null;
  generate: (params: GenerateParams) => void;
  reset: () => void;
}

class FatalStreamError extends Error {}

function buildQueryString(params: GenerateParams): string {
  const qs = new URLSearchParams();
  if (params.subject !== undefined) qs.append("subject", params.subject);
  if (params.grade !== undefined) qs.append("grade", String(params.grade));
  if (params.set_type !== undefined) qs.append("set_type", params.set_type);
  if (params.count !== undefined) qs.append("count", String(params.count));
  if (params.skip_verify !== undefined) qs.append("skip_verify", String(params.skip_verify));
  if (params.seed !== undefined) qs.append("seed", String(params.seed));
  if (params.image_generation_mode !== undefined) {
    qs.append("image_generation_mode", params.image_generation_mode);
  }
  for (const v of params.style ?? []) qs.append("style", v);
  for (const v of params.context ?? []) qs.append("context", v);
  for (const v of params.q_type ?? []) qs.append("q_type", v);
  if (params.subject_filter) qs.append("subject_filter", params.subject_filter);
  return qs.toString();
}

export function useGenerate(): UseGenerateReturn {
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [jobsAhead, setJobsAhead] = useState<number>(0);
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [results, setResults] = useState<ExamQuestion[]>([]);
  const [llmCalls, setLlmCalls] = useState<LlmCallEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
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
    setLlmCalls([]);
    setJobsAhead(0);
    setErrorMessage(null);
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
    setLlmCalls([]);
    setJobsAhead(0);
    setErrorMessage(null);

    fetchEventSource(url, {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      openWhenHidden: true,
      async onopen(res) {
        if (!res.ok) {
          if (res.status === 401) {
            useAuthStore.getState().logout();
          }
          const msg = res.status === 401
            ? "Session expired — please sign in again"
            : `Stream open failed: HTTP ${res.status}`;
          setErrorMessage(msg);
          throw new FatalStreamError(msg);
        }
      },
      onmessage(ev) {
        switch (ev.event) {
          case "queued": {
            const { jobs_ahead } = JSON.parse(ev.data) as { jobs_ahead: number };
            setJobsAhead(jobs_ahead);
            setStatus("queued");
            break;
          }
          case "started":
            setJobsAhead(0);
            setStatus("generating");
            break;
          case "progress":
            setProgressLines((prev) => [...prev, ev.data]);
            break;
          case "llm_request": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; model: string; messages: unknown[]; params?: unknown };
              setLlmCalls((prev) => [...prev, { type: "request", purpose: d.purpose, model: d.model, messages: d.messages, params: d.params }]);
            } catch { /* ignore */ }
            break;
          }
          case "llm_thinking": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; text: string };
              setLlmCalls((prev) => {
                const last = prev[prev.length - 1];
                if (last && last.type === "thinking" && last.purpose === d.purpose) {
                  return [...prev.slice(0, -1), { ...last, text: last.text + d.text }];
                }
                return [...prev, { type: "thinking", purpose: d.purpose, text: d.text }];
              });
            } catch { /* ignore */ }
            break;
          }
          case "llm_content": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; text: string };
              setLlmCalls((prev) => {
                const last = prev[prev.length - 1];
                if (last && last.type === "content" && last.purpose === d.purpose) {
                  return [...prev.slice(0, -1), { ...last, text: last.text + d.text }];
                }
                return [...prev, { type: "content", purpose: d.purpose, text: d.text }];
              });
            } catch { /* ignore */ }
            break;
          }
          case "llm_response": {
            try {
              const d = JSON.parse(ev.data) as { purpose: string; model: string; usage?: unknown };
              setLlmCalls((prev) => [...prev, { type: "response", purpose: d.purpose, model: d.model, usage: d.usage }]);
            } catch { /* ignore */ }
            break;
          }
          case "result":
            try {
              const parsed = JSON.parse(ev.data) as ExamQuestion;
              setResults((prev) => [...prev, parsed]);
            } catch {
              setStatus("error");
            }
            break;
          case "error":
            setErrorMessage(ev.data || "Unknown error");
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
        setErrorMessage(err instanceof Error ? err.message : String(err));
        setStatus("error");
        throw err instanceof Error ? err : new FatalStreamError(String(err));
      },
    }).catch(() => {
      // Stream terminated (abort or fatal error). State already updated.
    });
  }, []);

  return { status, jobsAhead, progressLines, results, llmCalls, errorMessage, generate, reset };
}
