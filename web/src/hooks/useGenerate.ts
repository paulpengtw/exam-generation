import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { useAuthStore } from "../store/authStore";

export type GenerateStatus = "idle" | "queued" | "generating" | "error";

export interface GenerateParams {
  subject?: string;
  grade?: number;
  style?: string[];
  content_type?: string;
  context?: string[];
  set_type?: string;
  q_type?: string[];
  count?: number;
  skip_verify?: boolean;
  seed?: number;
  image_generation_mode?: "html" | "gpt_image";
  subject_filter?: string;
  passage?: string;
  options?: string[];
  topic?: string;
  core_question?: string;
  sub_context?: string;
  science_competency?: string[];
  learning_performance?: string[];
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
  科學能力?: string[];
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
  題目內容類型?: string;
  情境子類別?: string;
  科學能力?: string[];
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
  | { type: "request"; purpose: string; agent: string; model: string; messages: unknown[]; params?: unknown }
  | { type: "thinking"; purpose: string; agent: string; text: string }
  | { type: "content"; purpose: string; agent: string; text: string }
  | { type: "response"; purpose: string; agent: string; model: string; usage?: unknown }
  | { type: "stage"; agent: string; stage: string; status: "start" | "end"; ts: number; retry?: number };

export type AgentStatus = "idle" | "running" | "done";

export interface AgentLane {
  agent: string;
  status: AgentStatus;
  currentStage: string | null;
  streamingThinking: string;
  streamingContent: string;
  stageHistory: Array<{ stage: string; startedAt: number; endedAt?: number; retry?: number }>;
}

function purposeToAgent(purpose: string): string {
  const map: Record<string, string> = {
    generate: "generator",
    verify: "verifier",
    correct: "corrector",
    html_image: "image_agent",
    plan: "planner",
  };
  return map[purpose] ?? purpose;
}

export interface UseGenerateReturn {
  status: GenerateStatus;
  jobsAhead: number;
  progressLines: string[];
  results: ExamQuestion[];
  llmCalls: LlmCallEvent[];
  agentLanes: AgentLane[];
  errorMessage: string | null;
  generate: (params: GenerateParams) => void;
  reset: () => void;
}

class FatalStreamError extends Error {}

function buildQueryString(params: GenerateParams): string {
  const qs = new URLSearchParams();
  if (params.subject !== undefined) qs.append("subject", params.subject);
  if (params.grade !== undefined) qs.append("grade", String(params.grade));
  if (params.content_type !== undefined) qs.append("content_type", params.content_type);
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
  if (params.passage) qs.append("passage", params.passage);
  for (const v of params.options ?? []) qs.append("options", v);
  if (params.topic) qs.append("topic", params.topic);
  if (params.core_question) qs.append("core_question", params.core_question);
  if (params.sub_context) qs.append("sub_context", params.sub_context);
  for (const v of params.science_competency ?? []) qs.append("science_competency", v);
  for (const v of params.learning_performance ?? []) qs.append("learning_performance", v);
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

  const sorted: AgentLane[] = [];
  for (const agent of AGENT_ORDER) {
    if (lanesMap.has(agent)) sorted.push(lanesMap.get(agent)!);
  }
  for (const [agent, lane] of lanesMap.entries()) {
    if (!AGENT_ORDER.includes(agent)) sorted.push(lane);
  }
  return sorted;
}

export function useGenerate(): UseGenerateReturn {
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [jobsAhead, setJobsAhead] = useState<number>(0);
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [results, setResults] = useState<ExamQuestion[]>([]);
  const [llmCalls, setLlmCalls] = useState<LlmCallEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

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
              const d = JSON.parse(ev.data) as { agent: string; stage: string; status: "start" | "end"; ts: number; retry?: number };
              setLlmCalls((prev) => [...prev, { type: "stage", agent: d.agent, stage: d.stage, status: d.status, ts: d.ts, retry: d.retry }]);
            } catch { /* ignore */ }
            break;
          }
          case "pipeline":
            // pipeline-level events (pipeline_start, question_start/end, pipeline_end) — no UI action needed beyond stage events
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

  return { status, jobsAhead, progressLines, results, llmCalls, agentLanes, errorMessage, generate, reset };
}
