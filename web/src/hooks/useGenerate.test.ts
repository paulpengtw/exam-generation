import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchEventSourceMock = vi.hoisted(() =>
  vi
    .fn<
      (
        input: RequestInfo,
        init: FetchEventSourceInit,
      ) => Promise<void>
    >()
    .mockResolvedValue(undefined),
);

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

const captureExceptionMock = vi.hoisted(() => vi.fn());
const isSentryEnabledMock = vi.hoisted(() => vi.fn().mockReturnValue(true));

vi.mock("@sentry/react", () => ({
  captureException: captureExceptionMock,
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: isSentryEnabledMock,
}));

// The buildQueryString helper is currently module-private. This test file
// intentionally imports it via a named re-export added in the implementation
// step below.
import {
  buildQueryString,
  parseErrorEventData,
  useGenerate,
  type VerificationTrailEntry,
} from "./useGenerate";
import { useLangStore } from "../store/langStore";

function latestStreamOptions(): FetchEventSourceInit {
  const call = fetchEventSourceMock.mock.lastCall;
  if (!call) {
    throw new Error("Expected generate() to open an event stream");
  }
  return call[1];
}

function renderStartedRun() {
  const hook = renderHook(() => useGenerate());
  act(() => {
    hook.result.current.generate({ subject: "math", count: 1 });
  });
  return hook;
}

describe("useGenerate — verification trail lanes", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockClear();
  });

  it("accumulates trail entries on the matching question lane", () => {
    const { result } = renderStartedRun();
    const question = (id: string) => ({
      id,
      情境: [],
      題型種類: "single",
      題型: "multiple_choice",
      題目: [id],
      正確解題分析: ["analysis"],
    });
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-1",
      timestamp: "2026-01-01T00:00:00+00:00",
      snapshot: { id: "q-1", 題目: ["before"] },
    };
    const passed: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "verification",
      question_id: "q-1",
      passed: true,
      details: "通過",
      my_answer: "A",
      provided_answer: "A",
      answer_match: true,
      chart_verification: null,
      model: "verify-model",
      timestamp: "2026-01-01T00:00:03+00:00",
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-1",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-01-01T00:00:02+00:00",
      snapshot: { id: "q-1", 題目: ["after"] },
    };
    const failed: VerificationTrailEntry = {
      ...passed,
      question_id: "q-2",
      passed: false,
      details: "需修正",
      timestamp: "2026-01-01T00:00:01+00:00",
    };

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({ index: 0, phase: "draft", question: question("q-1") }),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({ index: 1, phase: "draft", question: question("q-2") }),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(initial),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(failed),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(correction),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(passed),
      });
    });

    expect(result.current.displayResults.map((item) => item.trail)).toEqual([
      [initial, correction, passed],
      [failed],
    ]);
  });
});

describe("useGenerate — run timestamps", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000);
    fetchEventSourceMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("records the run start and clears both timestamps on reset", () => {
    const { result } = renderStartedRun();

    expect(result.current.startedAt).toBe(1_000);
    expect(result.current.finishedAt).toBeNull();

    act(() => {
      result.current.reset();
    });

    expect(result.current.startedAt).toBeNull();
    expect(result.current.finishedAt).toBeNull();
  });

  it("records the finish time when the stream sends done", () => {
    const { result } = renderStartedRun();
    vi.setSystemTime(5_000);

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "done",
        data: "",
      });
    });

    expect(result.current.finishedAt).toBe(5_000);
  });

  it("records the finish time when the stream sends an error event", () => {
    const { result } = renderStartedRun();
    vi.setSystemTime(6_000);

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "error",
        data: "generation failed",
      });
    });

    expect(result.current.finishedAt).toBe(6_000);
  });

  it("records the finish time when the stream error handler runs", () => {
    const { result } = renderStartedRun();
    vi.setSystemTime(7_000);
    let thrown: unknown;

    act(() => {
      try {
        latestStreamOptions().onerror?.(new Error("connection lost"));
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("connection lost"));
    expect(result.current.finishedAt).toBe(7_000);
  });

  it("records the finish time when opening the stream fails", async () => {
    const { result } = renderStartedRun();
    vi.setSystemTime(8_000);
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(null, { status: 500 }),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("Stream open failed: HTTP 500"));
    expect(result.current.finishedAt).toBe(8_000);
  });
});

describe("useGenerate — generation log identity", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockClear();
  });

  it("stores the ID announced by the started event and retains it through done", () => {
    const { result } = renderStartedRun();

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: "log-123" }),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "done",
        data: "{}",
      });
    });

    expect(result.current.generationLogId).toBe("log-123");
  });

  it("retains the ID when the server reports an error or the network disconnects", () => {
    const { result } = renderStartedRun();
    const stream = latestStreamOptions();

    act(() => {
      stream.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: "log-failed" }),
      });
      stream.onmessage?.({
        id: "",
        event: "error",
        data: "generation failed",
      });
    });

    expect(result.current.generationLogId).toBe("log-failed");

    act(() => {
      try {
        stream.onerror?.(new Error("connection lost"));
      } catch {
        // fetch-event-source uses the thrown error to stop retrying.
      }
    });

    expect(result.current.generationLogId).toBe("log-failed");
  });

  it("clears the ID on reset and ignores a late started event from the old run", () => {
    const { result } = renderStartedRun();
    const oldStream = latestStreamOptions();

    act(() => {
      oldStream.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: "old-log" }),
      });
    });
    expect(result.current.generationLogId).toBe("old-log");

    act(() => {
      oldStream.onmessage?.({ id: "", event: "done", data: "{}" });
      result.current.generate({ subject: "social_studies", count: 1 });
    });
    expect(result.current.generationLogId).toBeNull();

    act(() => {
      oldStream.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: "stale-log" }),
      });
    });
    expect(result.current.generationLogId).toBeNull();

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: "new-log" }),
      });
    });
    expect(result.current.generationLogId).toBe("new-log");

    act(() => {
      result.current.reset();
    });
    expect(result.current.generationLogId).toBeNull();
  });

  it.each(["", "{}"]) (
    "keeps a legacy started payload nullable (%j)",
    (data) => {
      const { result } = renderStartedRun();

      act(() => {
        latestStreamOptions().onmessage?.({ id: "", event: "started", data });
      });

      expect(result.current.generationLogId).toBeNull();
    },
  );
});

describe("useGenerate — resolved sub-question total", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockClear();
  });

  it("stores a plan announcement and clears it on reset", () => {
    const { result } = renderStartedRun();

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "plan",
        data: JSON.stringify({ sub_question_total: 5 }),
      });
    });

    expect(result.current.subQuestionTotal).toBe(5);

    act(() => {
      result.current.reset();
    });

    expect(result.current.subQuestionTotal).toBeNull();
  });

  it("clears the previous plan announcement when a new run starts", () => {
    const { result } = renderStartedRun();

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "plan",
        data: JSON.stringify({ sub_question_total: 5 }),
      });
    });
    expect(result.current.subQuestionTotal).toBe(5);

    act(() => {
      latestStreamOptions().onmessage?.({ id: "", event: "done", data: "{}" });
      result.current.generate({ subject: "social_studies", count: 1 });
    });

    expect(result.current.subQuestionTotal).toBeNull();
  });
});

describe("useGenerate — model overrides", () => {
  it("does not emit model_plan / model_execute when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });

  it("emits model_plan / model_execute when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "claude-opus-4-6",
      model_execute: "claude-haiku-4-6",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("model_plan")).toBe("claude-opus-4-6");
    expect(params.get("model_execute")).toBe("claude-haiku-4-6");
  });

  it("does not emit model_plan / model_execute when set to empty string", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "",
      model_execute: "",
    });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });
});

describe("buildQueryString — model_verify / model_correct overrides", () => {
  it("does not emit model_verify / model_correct when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("model_verify");
    expect(qs).not.toContain("model_correct");
  });

  it("emits model_verify / model_correct when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_verify: "claude-opus-4-6",
      model_correct: "claude-haiku-4-6",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("model_verify")).toBe("claude-opus-4-6");
    expect(params.get("model_correct")).toBe("claude-haiku-4-6");
  });

  it("does not emit model_verify / model_correct when set to empty string", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_verify: "",
      model_correct: "",
    });
    expect(qs).not.toContain("model_verify");
    expect(qs).not.toContain("model_correct");
  });
});

describe("buildQueryString — effort overrides", () => {
  it("does not emit effort_plan / effort_execute when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("effort_plan");
    expect(qs).not.toContain("effort_execute");
  });

  it("emits effort_plan / effort_execute when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      effort_plan: "high",
      effort_execute: "low",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("effort_plan")).toBe("high");
    expect(params.get("effort_execute")).toBe("low");
  });
});

describe("buildQueryString — effort_verify / effort_correct overrides", () => {
  it("does not emit effort_verify / effort_correct when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("effort_verify");
    expect(qs).not.toContain("effort_correct");
  });

  it("does not emit effort_verify / effort_correct when set to empty string", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      effort_verify: "",
      effort_correct: "",
    });
    expect(qs).not.toContain("effort_verify");
    expect(qs).not.toContain("effort_correct");
  });

  it("emits effort_verify / effort_correct when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      effort_verify: "high",
      effort_correct: "low",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("effort_verify")).toBe("high");
    expect(params.get("effort_correct")).toBe("low");
  });
});

describe("useGenerate — parseErrorEventData", () => {
  it("returns .message from a valid structured JSON payload", () => {
    const raw = JSON.stringify({ code: "generation_failed", message: "Question generation failed (RuntimeError)" });
    expect(parseErrorEventData(raw)).toBe("Question generation failed (RuntimeError)");
  });

  it("returns .message from a stream_failed payload", () => {
    const raw = JSON.stringify({ code: "stream_failed", message: "Stream error (ValueError)" });
    expect(parseErrorEventData(raw)).toBe("Stream error (ValueError)");
  });

  it("falls back to the raw string when the payload is not valid JSON", () => {
    expect(parseErrorEventData("something went wrong")).toBe("something went wrong");
  });

  it("falls back to the raw string when JSON lacks a message field", () => {
    const raw = JSON.stringify({ code: "generation_failed" });
    expect(parseErrorEventData(raw)).toBe(raw);
  });

  it("falls back to 'Unknown error' when the raw string is empty", () => {
    expect(parseErrorEventData("")).toBe("Unknown error");
  });

  it("falls back to the raw string for a plain string payload", () => {
    expect(parseErrorEventData("plain error text")).toBe("plain error text");
  });
});

describe("buildQueryString — text_word_limit serialization", () => {
  it("serializes text_word_limit when set", () => {
    const qs = buildQueryString({ subject: "social_studies", text_word_limit: 500 });
    expect(new URLSearchParams(qs).get("text_word_limit")).toBe("500");
  });

  it("omits text_word_limit when undefined", () => {
    const qs = buildQueryString({ subject: "math" });
    expect(qs).not.toContain("text_word_limit");
  });
});

describe("buildQueryString — text_instruction serialization", () => {
  it("serializes text_instruction when set", () => {
    const qs = buildQueryString({
      subject: "social_studies",
      text_instruction: "請聚焦地方自治中的證據比較",
    });

    expect(new URLSearchParams(qs).get("text_instruction")).toBe(
      "請聚焦地方自治中的證據比較",
    );
  });
});

describe("buildQueryString — drawn serialization", () => {
  it("serializes resolver provenance as repeated query values", () => {
    const params = {
      subject: "math",
      drawn: ["learning_content", "per_question_params[0].seed"],
    } as Parameters<typeof buildQueryString>[0];

    const qs = buildQueryString(params);

    expect(new URLSearchParams(qs).getAll("drawn")).toEqual([
      "learning_content",
      "per_question_params[0].seed",
    ]);
  });

  it("omits drawn when the optional metadata is absent", () => {
    const qs = buildQueryString({ subject: "math" });

    expect(qs).not.toContain("drawn");
  });
});

describe("buildQueryString — subject_filter as repeated keys", () => {
  it("sends subject_filter as two repeated keys for a two-element array", () => {
    const qs = buildQueryString({ subject: "social_studies", subject_filter: ["歷史", "地理"] });
    const params = new URLSearchParams(qs);
    expect(params.getAll("subject_filter")).toEqual(["歷史", "地理"]);
  });

  it("sends a single subject_filter as a single repeated key", () => {
    const qs = buildQueryString({ subject: "social_studies", subject_filter: ["歷史"] });
    const params = new URLSearchParams(qs);
    expect(params.getAll("subject_filter")).toEqual(["歷史"]);
  });

  it("omits subject_filter when the array is empty", () => {
    const qs = buildQueryString({ subject: "math", subject_filter: [] });
    expect(qs).not.toContain("subject_filter");
  });
});

describe("buildQueryString — core_competency as repeated keys", () => {
  it("emits every core_competency value when present", () => {
    const qs = buildQueryString({
      subject: "social_studies",
      core_competency: ["社-U-A1", "社-U-B2"],
    });

    expect(new URLSearchParams(qs).getAll("core_competency")).toEqual([
      "社-U-A1",
      "社-U-B2",
    ]);
  });

  it("omits core_competency when absent", () => {
    const qs = buildQueryString({ subject: "social_studies" });

    expect(qs).not.toContain("core_competency");
  });
});

describe("buildQueryString — math_thinking as repeated keys", () => {
  it("emits every math_thinking value when present", () => {
    const qs = buildQueryString({
      subject: "math",
      math_thinking: ["形成", "詮釋評估"],
    });

    expect(new URLSearchParams(qs).getAll("math_thinking")).toEqual([
      "形成",
      "詮釋評估",
    ]);
  });

  it("omits math_thinking when absent", () => {
    const qs = buildQueryString({ subject: "math" });

    expect(qs).not.toContain("math_thinking");
  });
});

describe("buildQueryString — per_question_params serialization", () => {
  it("emits the JSON array string unchanged", () => {
    const perQuestionParams = JSON.stringify([
      { difficulty: "easy", context: ["個人"] },
      { difficulty: "hard", context: ["公共"] },
    ]);

    const qs = buildQueryString({
      subject: "social_studies",
      count: 2,
      per_question_params: perQuestionParams,
    });

    expect(new URLSearchParams(qs).get("per_question_params")).toBe(perQuestionParams);
  });
});

describe("useGenerate — stream open error detail", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(8_000);
    fetchEventSourceMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not let a stale non-2xx open response update state after reset", async () => {
      const { result } = renderStartedRun();
      let resolveBody!: (body: unknown) => void;
      const bodyPromise = new Promise<unknown>((resolve) => {
        resolveBody = resolve;
      });
      const oldStream = latestStreamOptions();
      const pendingOpen = oldStream.onopen?.({
        ok: false,
        status: 422,
        json: () => bodyPromise,
      } as Response);

      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        result.current.reset();
      });

      await act(async () => {
        resolveBody({ detail: "old run failed" });
        await pendingOpen;
      });

      expect(result.current.errorMessage).toBeNull();
      expect(result.current.finishedAt).toBeNull();
      expect(result.current.status).toBe("idle");
    });

  it("surfaces the JSON detail field from the response body on a non-2xx open", async () => {
    const { result } = renderStartedRun();
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(
            JSON.stringify({ detail: "per_question_params[0] has unknown parameter(s): count" }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          ),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("per_question_params[0] has unknown parameter(s): count"));
    expect(result.current.errorMessage).toBe("per_question_params[0] has unknown parameter(s): count");
  });

  it("surfaces fielded completeness errors from a gate 422", async () => {
    const { result } = renderStartedRun();
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(
            JSON.stringify({
              detail: [
                { field: "per_question_params[0].學習內容", code: "unresolved" },
              ],
            }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          ),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(
      new Error("Incomplete request: per_question_params[0].學習內容 (unresolved)"),
    );
    expect(result.current.errorMessage).toBe(
      "Incomplete request: per_question_params[0].學習內容 (unresolved)",
    );
  });

  // #835: incompatible_parent / no_admitting_parent format through the
  // shared web/src/lib/resolverErrorMessages.ts formatter instead of the
  // legacy "field (code)" text — unlike `unresolved` above, which is
  // unchanged by #835.
  it("surfaces a readable incompatible_parent sentence (zh-TW) instead of the legacy code text", async () => {
    const originalLang = useLangStore.getState().lang;
    useLangStore.getState().setLang("zh-TW");
    try {
      const { result } = renderStartedRun();
      let thrown: unknown;

      await act(async () => {
        try {
          await latestStreamOptions().onopen?.(
            new Response(
              JSON.stringify({
                detail: [
                  { field: "learning_content", code: "incompatible_parent", parent: "地理" },
                ],
              }),
              { status: 422, headers: { "Content-Type": "application/json" } },
            ),
          );
        } catch (error) {
          thrown = error;
        }
      });

      expect(thrown).toEqual(new Error("所選的學習內容不屬於科目「地理」。"));
      expect(result.current.errorMessage).toBe("所選的學習內容不屬於科目「地理」。");
    } finally {
      useLangStore.getState().setLang(originalLang);
    }
  });

  it("surfaces a readable no_admitting_parent sentence (en-US) naming the question/小題 position", async () => {
    const originalLang = useLangStore.getState().lang;
    useLangStore.getState().setLang("en-US");
    try {
      const { result } = renderStartedRun();
      let thrown: unknown;

      await act(async () => {
        try {
          await latestStreamOptions().onopen?.(
            new Response(
              JSON.stringify({
                detail: [
                  {
                    field: "per_question_params[1].subquestion_configs[0].learning_content",
                    code: "no_admitting_parent",
                    parent: "科目",
                  },
                ],
              }),
              { status: 422, headers: { "Content-Type": "application/json" } },
            ),
          );
        } catch (error) {
          thrown = error;
        }
      });

      const expected =
        "In question 2, sub-question 1, the selected learning content has no common subject "
        + "available; remove some of the selected codes.";
      expect(thrown).toEqual(new Error(expected));
      expect(result.current.errorMessage).toBe(expected);
    } finally {
      useLangStore.getState().setLang(originalLang);
    }
  });

  it("falls back to the generic message when the body is not valid JSON", async () => {
    const { result } = renderStartedRun();
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response("Internal Server Error", { status: 500 }),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("Stream open failed: HTTP 500"));
    expect(result.current.errorMessage).toBe("Stream open failed: HTTP 500");
  });

  it("falls back to the generic message when the JSON body has no detail field", async () => {
    const { result } = renderStartedRun();
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(
            JSON.stringify({ error: "something went wrong" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("Stream open failed: HTTP 503"));
    expect(result.current.errorMessage).toBe("Stream open failed: HTTP 503");
  });

  it("preserves the 401 branch behaviour with no body read", async () => {
    const { result } = renderStartedRun();
    let thrown: unknown;

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(null, { status: 401 }),
        );
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toEqual(new Error("Session expired — please sign in again"));
    expect(result.current.errorMessage).toBe("Session expired — please sign in again");
  });
});

describe("useGenerate — Sentry capture on fatal stream failure", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockClear();
    captureExceptionMock.mockClear();
    isSentryEnabledMock.mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("captures a non-abort stream rejection in Sentry tagged as fetchEventSource", async () => {
    const fatalErr = new Error("Stream open failed: HTTP 422");
    fetchEventSourceMock.mockRejectedValueOnce(fatalErr);

    const { result } = renderHook(() => useGenerate());
    await act(async () => {
      result.current.generate({ subject: "math", count: 1 });
    });

    expect(captureExceptionMock).toHaveBeenCalledOnce();
    expect(captureExceptionMock).toHaveBeenCalledWith(
      fatalErr,
      expect.objectContaining({
        tags: expect.objectContaining({ source: "fetchEventSource" }),
      }),
    );
  });

  it("captures stream timing, message count, last event type, and online state", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);

    const fatalErr = new Error("connection lost");
    fetchEventSourceMock.mockImplementationOnce(async (_input, init) => {
      init.onmessage?.({ id: "", event: "stage", data: "" });
      init.onmessage?.({ id: "", event: "llm_content", data: "" });
      vi.setSystemTime(10_275);
      throw fatalErr;
    });

    const { result } = renderHook(() => useGenerate());
    await act(async () => {
      result.current.generate({ subject: "math", count: 1 });
    });

    expect(captureExceptionMock).toHaveBeenCalledWith(fatalErr, {
      tags: {
        source: "fetchEventSource",
        last_event_type: "llm_content",
        navigator_online: "false",
      },
      contexts: {
        stream: {
          elapsed_ms: 275,
          message_count: 2,
        },
      },
    });
  });

  it("does not capture an AbortError in Sentry (user-initiated abort)", async () => {
    const abortErr = Object.assign(new Error("The user aborted a request."), {
      name: "AbortError",
    });
    fetchEventSourceMock.mockRejectedValueOnce(abortErr);

    const { result } = renderHook(() => useGenerate());
    await act(async () => {
      result.current.generate({ subject: "math", count: 1 });
    });

    expect(captureExceptionMock).not.toHaveBeenCalled();
  });

  it("does not capture to Sentry when Sentry is disabled", async () => {
    isSentryEnabledMock.mockReturnValue(false);
    const fatalErr = new Error("connection lost");
    fetchEventSourceMock.mockRejectedValueOnce(fatalErr);

    const { result } = renderHook(() => useGenerate());
    await act(async () => {
      result.current.generate({ subject: "math", count: 1 });
    });

    expect(captureExceptionMock).not.toHaveBeenCalled();
  });
});

// Workspace additions deliberately leave the existing stream characterization cases intact.
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { exportResultsWorkspace, importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import type { ResultsWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import type { AdmissionOutcome } from "./useGenerate";

function sendWorkspaceEvent(event: string, data = "{}") {
  act(() => { latestStreamOptions().onmessage?.({ id: "", event, data }); });
}

describe("admission", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("waits for started, rather than HTTP success, and resolves the admission promise", async () => {
    const { result } = renderHook(() => useGenerate());
    expect(result.current.admission).toBe("idle");
    expect(result.current.admissionError).toBeNull();
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    expect(result.current.admission).toBe("submitting");
    expect(result.current.status).toBe("generating");
    await act(async () => { await latestStreamOptions().onopen?.(new Response()); });
    expect(result.current.admission).toBe("submitting");
    sendWorkspaceEvent("started");
    await expect(promise).resolves.toEqual({ outcome: "admitted" });
    expect(result.current.admission).toBe("admitted");
    sendWorkspaceEvent("error", "stream failed");
    expect(result.current.admission).toBe("admitted");
    expect(result.current.status).toBe("error");
    sendWorkspaceEvent("done");
    expect(result.current.admission).toBe("admitted");
    act(() => { result.current.reset(); });
    expect(result.current.admission).toBe("idle");
    expect(result.current.admissionError).toBeNull();
  });

  it.each([
    [401, "", "Session expired — please sign in again"],
    [422, JSON.stringify({ detail: [{ field: "grade", code: "unresolved" }] }), "Incomplete request: grade (unresolved)"],
    [500, "not JSON", "Stream open failed: HTTP 500"],
  ])("rejects HTTP %s with the existing error message", async (status, body, reason) => {
    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    await act(async () => {
      await expect(latestStreamOptions().onopen?.(new Response(body, { status }))).rejects.toThrow(reason);
    });
    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toBe(result.current.errorMessage);
    await expect(promise).resolves.toEqual({ outcome: "rejected", reason });
    expect(result.current.finishedAt).not.toBeNull();
  });

  it.each([false, true])("handles transport failure with started=%s", async (started) => {
    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    if (started) sendWorkspaceEvent("started");
    act(() => { expect(() => latestStreamOptions().onerror?.(new Error("connection lost"))).toThrow("connection lost"); });
    expect(result.current.admission).toBe(started ? "admitted" : "rejected");
    expect(result.current.admissionError).toBe(started ? null : "connection lost");
    await expect(promise).resolves.toEqual(started
      ? { outcome: "admitted" } : { outcome: "rejected", reason: "connection lost" });
  });

  it("ignores a duplicate run and keeps the active stream", async () => {
    const { result } = renderHook(() => useGenerate());
    let first!: Promise<AdmissionOutcome>;
    act(() => { first = result.current.generate({ subject: "math" }); });
    const active = latestStreamOptions();
    let duplicate!: Promise<AdmissionOutcome>;
    act(() => { duplicate = result.current.generate({ subject: "math" }); });
    await expect(duplicate).resolves.toEqual({
      outcome: "rejected",
      reason: "generation already in progress",
    });
    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    act(() => { active.onmessage?.({ id: "", event: "started", data: "{}" }); });
    expect(result.current.admission).toBe("admitted");
    expect(result.current.admissionError).toBeNull();
    act(() => { result.current.reset(); });
    await expect(first).resolves.toEqual({ outcome: "admitted" });
  });

  it("settles a pending admission on reset and unmount", async () => {
    const { result, unmount } = renderHook(() => useGenerate());
    let pending!: Promise<AdmissionOutcome>;
    act(() => { pending = result.current.generate({ subject: "math" }); });
    act(() => { result.current.reset(); });
    await expect(pending).resolves.toEqual({ outcome: "rejected", reason: "reset" });
    act(() => { pending = result.current.generate({ subject: "math" }); });
    unmount();
    await expect(pending).resolves.toEqual({ outcome: "rejected", reason: "aborted" });
  });
});

describe("restoreResults", () => {
  const question = { id: "restored", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["saved"], 正確解題分析: ["answer"] };
  const snapshot: ResultsWorkspaceSnapshot = {
    kind: "results", version: 1, results: [question],
    displayResults: [{ index: 0, question, isFinal: true }],
    progressLines: ["saved progress"], errorMessage: "saved error", startedAt: 100, finishedAt: 200,
    subQuestionTotal: 3, requestedTotal: 2, submittedSubQuestionCount: 3, completion: "settled",
  };

  it.each(["settled", "error", "unknown"] as const)("restores %s completion through the snapshot adapter", (completion) => {
    const { result } = renderStartedRun();
    sendWorkspaceEvent("started");
    sendWorkspaceEvent("llm_request", JSON.stringify({ purpose: "generate", model: "model", messages: [] }));
    expect(result.current.llmCalls).not.toHaveLength(0);
    sendWorkspaceEvent("done");
    const saved = importResultsWorkspace({ ...snapshot, completion })!;
    act(() => { expect(result.current.restoreResults(saved)).toBe(true); });
    expect(result.current).toMatchObject({
      results: snapshot.results, displayResults: snapshot.displayResults, progressLines: ["saved progress"],
      errorMessage: "saved error", startedAt: 100, finishedAt: 200, subQuestionTotal: 3,
      status: completion === "error" ? "error" : "idle", admission: "idle", admissionError: null, llmCalls: [],
    });
    expect(exportResultsWorkspace({ ...result.current, requestedTotal: 2, submittedSubQuestionCount: 3 })).toMatchObject({
      ...snapshot,
      completion: completion === "settled" ? "unknown" : completion,
    });
  });

  it("refuses restoration during a live stream without changing state", () => {
    const { result } = renderStartedRun();
    const before = result.current;
    act(() => { expect(result.current.restoreResults(snapshot)).toBe(false); });
    expect(result.current).toBe(before);
    expect(latestStreamOptions().signal?.aborted).toBe(false);
  });
});

describe("workspace operation", () => {
  const originalBeginOperation = useWorkspaceStore.getState().beginOperation;
  beforeEach(() => { resetWorkspaceStoreForTests(); });
  afterEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({ beginOperation: originalBeginOperation });
  });

  it.each([
    ["done", "completed"], ["error", "failed"], ["onerror", "failed"],
    ["onopen", "failed"], ["reset", "aborted"], ["unmount", "aborted"],
  ] as const)("ends generation on %s as %s", async (event, outcome) => {
    const begin = useWorkspaceStore.getState().beginOperation;
    const end = vi.fn();
    vi.spyOn(useWorkspaceStore.getState(), "beginOperation").mockImplementation((...args) => {
      const handle = begin(...args);
      return { id: handle.id, end: (value) => { end(value); handle.end(value); } };
    });
    const { result, unmount } = renderStartedRun();
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ kind: "generation", surface: "generate.results" }),
    ]);
    if (event === "reset") act(() => { result.current.reset(); });
    else if (event === "unmount") unmount();
    else if (event === "onerror") act(() => { expect(() => latestStreamOptions().onerror?.(new Error("lost"))).toThrow(); });
    else if (event === "onopen") await act(async () => { await expect(latestStreamOptions().onopen?.(new Response("", { status: 500 }))).rejects.toThrow(); });
    else sendWorkspaceEvent(event);
    expect(end).toHaveBeenCalledWith(outcome);
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
    unmount();
  });
});

// ---------------------------------------------------------------------------
// F3: Generation stream v2 — hook integration tests
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { RunEvidenceState } from "../lib/generationEvidence";

function sendV2Event(event: string, context: Record<string, unknown>, payload: unknown) {
  act(() => {
    latestStreamOptions().onmessage?.({
      id: "",
      event,
      data: JSON.stringify({ context, payload }),
    });
  });
}

const V2_STARTED_DATA = {
  context: { run_id: "RUN", event_seq: 1 },
  payload: {
    protocol_version: 2,
    total: 2,
    questions: [
      { index: 0, question_id: "q_RUN_001" },
      { index: 1, question_id: "q_RUN_002" },
    ],
    generation_log_id: null,
  },
};

const sampleQ = (id: string) => ({
  id,
  情境: ["個人"],
  題型種類: "單一題",
  題型: "選擇題",
  題目: [`question for ${id}`],
  正確解題分析: ["answer"],
  出題概念: "",
  誘答分析: {},
});

describe("F3: stream_version 2 in POST body", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sends stream_version 2 in the POST body", () => {
    renderStartedRun();
    const opts = latestStreamOptions();
    const body = JSON.parse(opts.body as string);
    expect(body.stream_version).toBe(2);
  });
});

describe("F3: v2 fixture replay", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("replays math_single_interleaved.jsonl: 2 placeholders after started, B filled first, 2/2 at done", () => {
    const fixtureLines = readFileSync(
      resolve(__dirname, "../../../tests/fixtures/generation_v2/math_single_interleaved.jsonl"),
      "utf-8",
    ).trim().split("\n").map((l) => JSON.parse(l) as {
      event: string;
      context: Record<string, unknown>;
      payload: unknown;
    });

    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math", count: 2 }); });

    // Assert stream_version 2 in body
    const body = JSON.parse(latestStreamOptions().body as string);
    expect(body.stream_version).toBe(2);

    let bFilledBeforeA = false;
    let aFilled = false;

    for (const line of fixtureLines) {
      act(() => {
        latestStreamOptions().onmessage?.({
          id: "",
          event: line.event,
          data: JSON.stringify({ context: line.context, payload: line.payload }),
        });
      });
      const ev = result.current as unknown as { evidence: RunEvidenceState | null };
      const evState = ev.evidence;
      if (!evState) continue;

      // Check placeholders after started
      if (line.event === "started") {
        expect(evState.total).toBe(2);
        expect(evState.order).toEqual(["q_RUN_001", "q_RUN_002"]);
        expect(evState.questions["q_RUN_001"].content.receipt).toBe("none");
        expect(evState.questions["q_RUN_002"].content.receipt).toBe("none");
      }

      // Check B filled before A (B is index 1, result arrives at seq 18)
      if (evState.questions["q_RUN_002"].content.receipt === "final" && evState.questions["q_RUN_001"].content.receipt !== "final") {
        bFilledBeforeA = true;
      }
      if (evState.questions["q_RUN_001"].content.receipt === "final") {
        aFilled = true;
      }
    }

    expect(bFilledBeforeA).toBe(true);
    expect(aFilled).toBe(true);

    const finalEv = result.current as unknown as { evidence: RunEvidenceState | null };
    const finalState = finalEv.evidence!;
    expect(finalState.closed).toBe(true);
    // Both questions have terminals (ended count)
    const endedCount = Object.values(finalState.questions).filter((q) => q.terminal !== null).length;
    expect(endedCount).toBe(2);
    // Both have final receipt
    const finalCount = Object.values(finalState.questions).filter((q) => q.content.receipt === "final").length;
    expect(finalCount).toBe(2);
  });
});

describe("F3: unknown protocol → abort and error", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets status error on unknown_protocol and does not call generate a second time", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({
          context: { run_id: "RUN", event_seq: 1 },
          payload: { protocol_version: 99, total: 1, questions: [{ index: 0, question_id: "q1" }] },
        }),
      });
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1); // no retry
  });
});

describe("F3: missing started then done → no placeholders, error", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets status error and no evidence when done arrives before started", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "done",
        data: JSON.stringify({ context: { run_id: "RUN", event_seq: 1 }, payload: {} }),
      });
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    const ev = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev.evidence).toBeNull();
  });
});

describe("F3: stale started from previous generation ignored", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("ignores a duplicate without replacing the active generation", async () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });
    const activeOpts = latestStreamOptions();

    let duplicate!: Promise<AdmissionOutcome>;
    act(() => { duplicate = result.current.generate({ subject: "math" }); });
    await expect(duplicate).resolves.toEqual({
      outcome: "rejected",
      reason: "generation already in progress",
    });
    expect(result.current.admission).toBe("submitting");

    // The active connection remains the only connection.
    act(() => {
      activeOpts.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // Evidence is accepted from the active connection.
    const ev = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev.evidence).not.toBeNull();
    expect(result.current.admission).toBe("admitted");
  });
});

describe("F3: terminal-before-final then final fills", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("shows finalPending then cleared when final arrives after terminal", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    // v2 started
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "", event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // terminal arrives for q_RUN_001 before result
    sendV2Event("question_terminal", { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    });

    const ev1 = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev1.evidence?.questions["q_RUN_001"].finalPending).toBe(true);

    // now result arrives
    sendV2Event("result", { run_id: "RUN", event_seq: 3, question_id: "q_RUN_001", index: 0, content_revision: 1 }, sampleQ("q_RUN_001"));

    const ev2 = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev2.evidence?.questions["q_RUN_001"].finalPending).toBe(false);
    expect(ev2.evidence?.questions["q_RUN_001"].content.receipt).toBe("final");
  });
});

describe("F3: final without terminal then done → processing unknown", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("leaves processing unknown when stream closes without terminal", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({ id: "", event: "started", data: JSON.stringify(V2_STARTED_DATA) });
    });

    // result for q_RUN_001 without terminal
    sendV2Event("result", { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", index: 0, content_revision: 1 }, sampleQ("q_RUN_001"));

    // done
    sendV2Event("done", { run_id: "RUN", event_seq: 3 }, {});

    const ev = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev.evidence?.questions["q_RUN_001"].processing).toBe("unknown");
    expect(ev.evidence?.questions["q_RUN_001"].content.receipt).toBe("final");
    expect(ev.evidence?.closed).toBe(true);
  });
});

describe("F3: v2 displayResults carry stableId and contentRevision", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets stableId = question_id and contentRevision from context.content_revision on question_update", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "", event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // Send question_update for q_RUN_001 with content_revision 3
    // payload must have { question, phase } — the evidence reducer reads payload.question
    sendV2Event(
      "question_update",
      { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", index: 0, content_revision: 3 },
      { question: sampleQ("q_RUN_001"), phase: "draft" },
    );

    const dr = result.current.displayResults;
    expect(dr).toHaveLength(1);
    expect(dr[0].stableId).toBe("q_RUN_001");
    expect(dr[0].contentRevision).toBe(3);
  });

  it("sets stableId = question_id and contentRevision from context.content_revision on result", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "", event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // Send result for q_RUN_001 with content_revision 5
    sendV2Event(
      "result",
      { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", index: 0, content_revision: 5 },
      sampleQ("q_RUN_001"),
    );

    const dr = result.current.displayResults;
    expect(dr).toHaveLength(1);
    expect(dr[0].stableId).toBe("q_RUN_001");
    expect(dr[0].contentRevision).toBe(5);
  });

});

describe("F3: v2 error event sets resultsCompletion to 'error'", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets resultsCompletion to 'error' when a v2 error event arrives", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "", event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    sendV2Event("error", { run_id: "RUN", event_seq: 2 }, { message: "something went wrong" });

    const r = result.current as unknown as { resultsCompletion: string | null; terminalEvidence: boolean };
    expect(result.current.status).toBe("error");
    expect(r.resultsCompletion).toBe("error");
    expect(r.terminalEvidence).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Gap 4 tests (issue #750 code review)
// ---------------------------------------------------------------------------

describe("useGenerate — unknown stream version stays unsupported (issue #750 gap 4b)", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets status=error and errorMessage when started carries unknown protocol_version, no resubmit", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math", count: 1 }); });

    const callCountBefore = fetchEventSourceMock.mock.calls.length;

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({
          context: { run_id: "RUN" },
          payload: { protocol_version: 99, total: 1, questions: [] },
        }),
      });
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    // No additional fetchEventSource calls (no auto-resubmit)
    expect(fetchEventSourceMock.mock.calls.length).toBe(callCountBefore);
  });
});

describe("useGenerate — disconnect mid-legacy-stream retains received content (issue #750 gap 4c)", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("retains received legacy questions and marks resultsCompletion=error on onerror", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math", count: 2 }); });

    const stream = latestStreamOptions();
    const question1 = {
      id: "q-1",
      情境: [],
      題型種類: "single",
      題型: "multiple_choice",
      題目: ["Legacy Q1"],
      正確解題分析: ["answer"],
    };

    act(() => {
      // started event → legacy mode
      stream.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({ generation_log_id: null }),
      });
      // one question_update arrives
      stream.onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({ index: 0, phase: "draft", question: question1 }),
      });
    });

    // Verify question was received
    expect(result.current.displayResults).toHaveLength(1);
    expect(result.current.displayResults[0].question.題目).toEqual(["Legacy Q1"]);

    // Simulate disconnect
    act(() => {
      try { stream.onerror?.(new Error("connection lost")); } catch { /* expected */ }
    });

    // Content is retained after disconnect
    expect(result.current.displayResults).toHaveLength(1);
    expect(result.current.displayResults[0].question.題目).toEqual(["Legacy Q1"]);
    expect(result.current.status).toBe("error");

    // No second fetchEventSource call issued
    expect(fetchEventSourceMock.mock.calls.length).toBe(1);
  });
});

describe("useGenerate — legacy fixture replay end-to-end (issue #750 gap 4e)", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("replays math_single_legacy.jsonl and produces two correctly-ordered questions", () => {
    // Load the real fixture derived from pre-v2 server format (sha 35a7219)
    const fixturePath = resolve(
      __dirname,
      "../../../tests/fixtures/generation_legacy/math_single_legacy.jsonl",
    );
    const lines = readFileSync(fixturePath, "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event: string; data: string });

    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math", count: 2 }); });

    act(() => {
      for (const line of lines) {
        latestStreamOptions().onmessage?.({
          id: "",
          event: line.event,
          data: line.data,
        });
      }
    });

    // Two questions with final content
    const dr = result.current.displayResults;
    expect(dr).toHaveLength(2);
    // Both questions received their final result events
    expect(dr.every((item) => item.isFinal)).toBe(true);
    // Index ordering: 0 before 1 (both have explicit resolvedIndex from question_update)
    expect(dr[0].index).toBeLessThan(dr[1].index);
    // No placeholder cards (adapter never pre-allocates)
    expect(dr.every((item) => item.question.題目.length > 0)).toBe(true);
    // positionUnknown not set (both questions had explicit index in question_update)
    expect(dr.every((item) => !item.positionUnknown)).toBe(true);
    // Status is idle (stream completed)
    expect(result.current.status).toBe("idle");
  });
});

// ---------------------------------------------------------------------------
// Task 5.1 gap-fill tests (issue #895)
// ---------------------------------------------------------------------------

describe("F3: invalid manifest in started → no v2 slots, status error", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets status error and no evidence when started carries an invalid manifest (total mismatch)", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify({
          context: { run_id: "RUN", event_seq: 1 },
          payload: {
            protocol_version: 2,
            total: 3, // mismatch: total says 3 but only 2 questions listed
            questions: [
              { index: 0, question_id: "q_RUN_001" },
              { index: 1, question_id: "q_RUN_002" },
            ],
          },
        }),
      });
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    const ev = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(ev.evidence).toBeNull();
  });
});

describe("F3: second started in active v2 run does not overwrite slots", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("ignores a second identical started (same payload, same seq 1) and preserves accumulated evidence content", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    // First valid v2 started → evidence with 2 slots (receipt=none)
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // Deliver a draft for q_RUN_001 at seq 2 so receipt advances to "draft"
    sendV2Event("question_update",
      { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", content_revision: 1 },
      { question: { ...sampleQ("q_RUN_001") } },
    );

    expect((result.current as unknown as { evidence: RunEvidenceState | null }).evidence!.questions["q_RUN_001"].content.receipt).toBe("draft");

    // Second identical started: seq 1 already seen → duplicate_seq ignore; started case NOT triggered
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    // Evidence is NOT reset — draft content from q_RUN_001 is still present
    const evAfter = (result.current as unknown as { evidence: RunEvidenceState | null }).evidence;
    expect(evAfter).not.toBeNull();
    expect(evAfter!.total).toBe(2);
    expect(evAfter!.questions["q_RUN_001"].content.receipt).toBe("draft");
    // Status stays generating (not error)
    expect(result.current.status).toBe("generating");
  });
});

describe("F3: HTTP 426 → stops, no resubmit", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("sets status error on HTTP 426 and does not issue a second generate call", async () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(
            JSON.stringify({
              detail: "介面版本已更新，請重新整理頁面後再生成。",
              code: "CLIENT_UPDATE_REQUIRED",
              supported_stream_versions: [2],
            }),
            { status: 426, headers: { "Content-Type": "application/json" } },
          ),
        );
      } catch { /* expected: FatalStreamError thrown on non-2xx */ }
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    // No second fetchEventSource call (no resubmit on 426)
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
  });
});

describe("F3: stale events from previous connection do not affect new connection", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("stale done from old connection does not corrupt the new connection's evidence or status", () => {
    const { result } = renderHook(() => useGenerate());

    // --- First generate: run "RUN" (2 questions) ---
    act(() => { result.current.generate({ subject: "math" }); });
    const oldStream = latestStreamOptions();

    // started seq 1 → v2 mode, evidence created
    act(() => {
      oldStream.onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });
    // question_update seq 2 → q_RUN_001 draft
    act(() => {
      oldStream.onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({
          context: { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", content_revision: 1 },
          payload: { question: { ...sampleQ("q_RUN_001") } },
        }),
      });
    });
    expect((result.current as unknown as { evidence: RunEvidenceState | null }).evidence!
      .questions["q_RUN_001"].content.receipt).toBe("draft");

    // Reset clears the first connection
    act(() => { result.current.reset(); });

    // --- Second generate: run "RUN2" (2 different questions) ---
    act(() => { result.current.generate({ subject: "math" }); });

    const RUN2_STARTED_DATA = {
      context: { run_id: "RUN2", event_seq: 1 },
      payload: {
        protocol_version: 2,
        total: 2,
        questions: [
          { index: 0, question_id: "q_RUN2_001" },
          { index: 1, question_id: "q_RUN2_002" },
        ],
        generation_log_id: null,
      },
    };

    // New connection: started RUN2
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(RUN2_STARTED_DATA),
      });
    });
    // New connection: question_update seq 2 → q_RUN2_001 draft
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({
          context: { run_id: "RUN2", event_seq: 2, question_id: "q_RUN2_001", content_revision: 1 },
          payload: { question: { ...sampleQ("q_RUN2_001") } },
        }),
      });
    });
    const evNew = (result.current as unknown as { evidence: RunEvidenceState | null }).evidence;
    expect(evNew).not.toBeNull();
    expect(evNew!.runId).toBe("RUN2");
    expect(evNew!.total).toBe(2);
    expect(evNew!.order).toEqual(["q_RUN2_001", "q_RUN2_002"]);
    expect(evNew!.questions["q_RUN2_001"].content.receipt).toBe("draft");
    expect(result.current.status).toBe("generating");

    // --- OLD stream fires stale "done" for RUN (seq 3) ---
    // The decoder for the first connection has seqNextExpected=3, so this is next in order.
    // With the controller guard (controllerRef.current !== controller), this is blocked.
    // Without the guard, handleV2Event("done") would set status="idle" and null out controllerRef.
    act(() => {
      oldStream.onmessage?.({
        id: "",
        event: "done",
        data: JSON.stringify({ context: { run_id: "RUN", event_seq: 3 }, payload: {} }),
      });
    });

    // New connection's evidence is unchanged
    const evAfterStale = (result.current as unknown as { evidence: RunEvidenceState | null }).evidence;
    expect(evAfterStale).not.toBeNull();
    expect(evAfterStale!.runId).toBe("RUN2");
    expect(evAfterStale!.total).toBe(2);
    expect(evAfterStale!.questions["q_RUN2_001"].content.receipt).toBe("draft");
    // Status is still generating (stale done did not terminate the new run)
    expect(result.current.status).toBe("generating");
  });
});

describe("F3: only valid started creates v2 evidence slots", () => {
  beforeEach(() => { fetchEventSourceMock.mockClear(); });

  it("pre-started question_update does not create v2 evidence; valid started creates the manifest slots", () => {
    const { result } = renderHook(() => useGenerate());
    act(() => { result.current.generate({ subject: "math" }); });

    // Send a question_update before started: decoder is in awaiting-start → held → processed as legacy
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({
          index: 0,
          phase: "draft",
          question: { id: "q_early", 題目: ["early question"], 正確解題分析: ["answer"], 情境: [], 題型種類: "單一題", 題型: "選擇題" },
        }),
      });
    });

    // No v2 evidence slots before started
    const evBefore = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(evBefore.evidence).toBeNull();

    // Now valid v2 started arrives → creates 2 manifest slots, clears legacy results
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "started",
        data: JSON.stringify(V2_STARTED_DATA),
      });
    });

    const evAfter = result.current as unknown as { evidence: RunEvidenceState | null };
    expect(evAfter.evidence).not.toBeNull();
    expect(evAfter.evidence!.total).toBe(2);
    expect(evAfter.evidence!.order).toEqual(["q_RUN_001", "q_RUN_002"]);
    // Both slots have receipt=none (pre-started content is NOT in the v2 slots)
    expect(evAfter.evidence!.questions["q_RUN_001"].content.receipt).toBe("none");
    expect(evAfter.evidence!.questions["q_RUN_002"].content.receipt).toBe("none");
  });
});
