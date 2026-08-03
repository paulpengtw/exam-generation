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
} from "./useGenerate";

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

  it("captures a non-abort stream rejection in Sentry tagged as fetchEventSource", async () => {
    const fatalErr = new Error("Stream open failed: HTTP 422");
    fetchEventSourceMock.mockRejectedValueOnce(fatalErr);

    const { result } = renderHook(() => useGenerate());
    await act(async () => {
      result.current.generate({ subject: "math", count: 1 });
    });

    expect(captureExceptionMock).toHaveBeenCalledOnce();
    expect(captureExceptionMock).toHaveBeenCalledWith(fatalErr, {
      tags: { source: "fetchEventSource" },
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
