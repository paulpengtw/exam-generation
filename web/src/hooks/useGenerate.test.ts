import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const captureExceptionMock = vi.hoisted(() => vi.fn());
const isSentryEnabledMock = vi.hoisted(() => vi.fn().mockReturnValue(true));
// fetchEventSource mock — starts as a no-op; individual test suites configure it.
const fetchEventSourceMock = vi.hoisted(() => vi.fn<
  [string, { onopen?: (r: Response) => Promise<void> | void; onmessage?: (ev: { event: string; data: string; id?: string; retry?: number }) => void; onerror?: (err: unknown) => void; onclose?: () => void; signal?: AbortSignal; openWhenHidden?: boolean; headers?: Record<string, string>; method?: string }],
  Promise<void>
>().mockResolvedValue(undefined));

vi.mock("@sentry/react", () => ({
  captureException: captureExceptionMock,
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: isSentryEnabledMock,
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

import {
  buildQueryString,
  parseErrorPayload,
  RUN_POLL_HIDDEN_MS,
  RUN_POLL_VISIBLE_MS,
  useGenerate,
  type AdmissionOutcome,
} from "./useGenerate";
import { useLangStore } from "../store/langStore";
import { MESSAGES } from "../i18n/messages";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import {
  acceptedRun,
  endedQuestion,
  examQuestion,
  runningQuestion,
  runSnapshot,
  waitingQuestion,
} from "../test/runFixtures";
import { selectEndedCount, selectFinalReceivedCount } from "../lib/generationEvidence";
import {
  resetWorkspaceStoreForTests,
  useWorkspaceStore,
} from "../lib/workspace/workspaceStore";
import { exportResultsWorkspace, importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import type { ResultsWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import type { VerificationTrailEntry } from "./useGenerate";

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000);
  server = installFakeRunServer();
  captureExceptionMock.mockClear();
  isSentryEnabledMock.mockReturnValue(true);
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** Let a resolved fetch / Response.json() chain and any due timers run. */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

afterEach(() => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
});

/** Start a run and flush until it is accepted (polling armed). */
async function startRun(count = 1, snapshot = runSnapshot(
  Array.from({ length: count }, (_, i) => waitingQuestion(`q-${i + 1}`)),
)) {
  server.setSnapshot("run-1", snapshot);
  const hook = renderHook(() => useGenerate());
  let admission!: Promise<AdmissionOutcome>;
  act(() => {
    admission = hook.result.current.generate({ subject: "math", count });
  });
  await flush();
  return { ...hook, admission };
}

describe("useGenerate — submit (issue #908)", () => {
  it("submits POST /api/generate with stream_version 3 and the build header", async () => {
    const { result, admission } = await startRun(2);

    expect(server.submits()).toHaveLength(1);
    const [submit] = server.submits();
    expect(submit.url).toBe("/api/generate");
    expect(submit.body).toMatchObject({ subject: "math", count: 2, stream_version: 3 });
    expect(submit.headers["x-frontend-build-id"]).toBe("test-build-id");
    await expect(admission).resolves.toEqual({ outcome: "admitted", runId: "run-1" });
    expect(result.current.admission).toBe("admitted");
  });

  it("builds the query spelling with stream_version 3 too", () => {
    expect(new URLSearchParams(buildQueryString({ subject: "math" })).get("stream_version")).toBe("3");
  });

  it("builds evidence from the 202 manifest: every question waiting, run id known", async () => {
    server.setAcceptance(acceptedRun(3, "run-9"));
    server.setSnapshot("run-9", runSnapshot(
      [waitingQuestion("q-1"), waitingQuestion("q-2"), waitingQuestion("q-3")],
      { run_id: "run-9" },
    ));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math", count: 3 }); });
    await flush();

    expect(result.current.runId).toBe("run-9");
    expect(result.current.generationLogId).toBe("run-9");
    expect(result.current.status).toBe("generating");
    expect(result.current.evidence?.order).toEqual(["q-1", "q-2", "q-3"]);
    expect(result.current.evidence?.questions["q-2"].processing).toBe("waiting");
    expect(result.current.startedAt).toBe(1_000);
  });

  it("rejects a 202 whose protocol version is not 3 and shows the localized error", async () => {
    server.setAcceptance({ ...acceptedRun(1), protocol_version: 2 });
    const { result } = renderHook(() => useGenerate());
    let outcome!: Promise<AdmissionOutcome>;
    act(() => { outcome = result.current.generate({ subject: "math", count: 1 }); });
    await flush();

    await expect(outcome).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBeTruthy();
    expect(server.polls()).toHaveLength(0);
  });

  it("stops on HTTP 426 with the update message and does not resubmit", async () => {
    server.failSubmit(426, {
      detail: "介面版本已更新，請重新整理頁面後再生成。",
      code: "CLIENT_UPDATE_REQUIRED",
      supported_stream_versions: [3],
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();
    await flush(RUN_POLL_VISIBLE_MS * 3);

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBe("介面版本已更新，請重新整理頁面後再生成。");
    expect(server.submits()).toHaveLength(1);
    expect(server.polls()).toHaveLength(0);
  });

  it("does not let a stale failure response update state after reset", async () => {
    const { result } = renderHook(() => useGenerate());
    let resolveBody!: (body: unknown) => void;
    const bodyPromise = new Promise<unknown>((resolve) => { resolveBody = resolve; });
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 422,
      json: () => bodyPromise,
    })));

    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();
    act(() => { result.current.reset(); });
    await act(async () => {
      resolveBody({ detail: "old run failed" });
      await Promise.resolve();
    });

    expect(result.current.errorMessage).toBeNull();
    expect(result.current.finishedAt).toBeNull();
    expect(result.current.status).toBe("idle");
  });
});

describe("useGenerate — submit error detail", () => {
  it("surfaces the JSON detail field from the response body", async () => {
    server.failSubmit(422, { detail: "per_question_params[0] has unknown parameter(s): count" });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.errorMessage).toBe("per_question_params[0] has unknown parameter(s): count");
    expect(result.current.admissionError).toBe(result.current.errorMessage);
    expect(result.current.finishedAt).not.toBeNull();
  });

  it("surfaces fielded completeness errors from a gate 422", async () => {
    server.failSubmit(422, {
      detail: [{ field: "per_question_params[0].學習內容", code: "unresolved" }],
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

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
      server.failSubmit(422, {
        detail: [{ field: "learning_content", code: "incompatible_parent", parent: "地理" }],
      });
      const { result } = renderHook(() => useGenerate());
      act(() => { void result.current.generate({ subject: "math" }); });
      await flush();

      expect(result.current.errorMessage).toBe("所選的學習內容不屬於科目「地理」。");
    } finally {
      useLangStore.getState().setLang(originalLang);
    }
  });

  it("surfaces a readable no_admitting_parent sentence (en-US) naming the question/小題 position", async () => {
    const originalLang = useLangStore.getState().lang;
    useLangStore.getState().setLang("en-US");
    try {
      server.failSubmit(422, {
        detail: [{
          field: "per_question_params[1].subquestion_configs[0].learning_content",
          code: "no_admitting_parent",
          parent: "科目",
        }],
      });
      const { result } = renderHook(() => useGenerate());
      act(() => { void result.current.generate({ subject: "math" }); });
      await flush();

      expect(result.current.errorMessage).toBe(
        "In question 2, sub-question 1, the selected learning content has no common subject "
        + "available; remove some of the selected codes.",
      );
    } finally {
      useLangStore.getState().setLang(originalLang);
    }
  });

  it("falls back to the generic message when the body is not valid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Internal Server Error", { status: 500 })));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.errorMessage).toBe("Submit failed: HTTP 500");
  });

  it("falls back to the generic message when the JSON body has no detail field", async () => {
    server.failSubmit(503, { error: "something went wrong" });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.errorMessage).toBe("Submit failed: HTTP 503");
  });

  it("preserves the 401 branch behaviour with no body read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.errorMessage).toBe("Session expired — please sign in again");
    expect(result.current.status).toBe("error");
  });
});

describe("useGenerate — Sentry capture on a failed submission", () => {
  it("captures a submit network failure tagged as generateSubmit", async () => {
    const networkErr = new TypeError("Failed to fetch");
    vi.stubGlobal("fetch", vi.fn(async () => { throw networkErr; }));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math", count: 1 }); });
    await flush();

    expect(captureExceptionMock).toHaveBeenCalledOnce();
    expect(captureExceptionMock).toHaveBeenCalledWith(
      networkErr,
      expect.objectContaining({
        tags: expect.objectContaining({ source: "generateSubmit" }),
      }),
    );
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBe("Failed to fetch");
  });

  it("does not capture to Sentry when Sentry is disabled", async () => {
    isSentryEnabledMock.mockReturnValue(false);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math", count: 1 }); });
    await flush();

    expect(captureExceptionMock).not.toHaveBeenCalled();
  });

  it("captures an HTTP rejection with only its message, as before the detached transport", async () => {
    server.failSubmit(422, { detail: "nope", input: "PRIVATE_INPUT" });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math", count: 1 }); });
    await flush();

    expect(captureExceptionMock).toHaveBeenCalledOnce();
    const [error, context] = captureExceptionMock.mock.calls[0];
    expect(error).toEqual(new Error("nope"));
    expect(`${error.message} ${JSON.stringify(context)}`).not.toContain("PRIVATE_");
  });
});

describe("useGenerate — polling cadence", () => {
  it("polls GET /api/runs/{id} every ~3 s while the page is visible", async () => {
    await startRun();
    expect(server.polls()).toHaveLength(0);

    await flush(RUN_POLL_VISIBLE_MS - 1);
    expect(server.polls()).toHaveLength(0);
    await flush(1);
    expect(server.polls()).toHaveLength(1);
    expect(server.polls()[0].url).toBe("/api/runs/run-1");

    await flush(RUN_POLL_VISIBLE_MS);
    expect(server.polls()).toHaveLength(2);
    await flush(RUN_POLL_VISIBLE_MS);
    expect(server.polls()).toHaveLength(3);
  });

  it("polls slower while the document is hidden and speeds up when visible again", async () => {
    await startRun();
    await flush(RUN_POLL_VISIBLE_MS);
    expect(server.polls()).toHaveLength(1);

    act(() => setVisibility("hidden"));
    await flush(RUN_POLL_VISIBLE_MS * 3);
    expect(server.polls()).toHaveLength(1);
    await flush(RUN_POLL_HIDDEN_MS - RUN_POLL_VISIBLE_MS * 3);
    expect(server.polls()).toHaveLength(2);

    // Coming back: the overdue poll happens right away, then 3 s cadence resumes.
    await flush(RUN_POLL_HIDDEN_MS - 1_000);
    act(() => setVisibility("visible"));
    await flush(0);
    expect(server.polls()).toHaveLength(3);
    await flush(RUN_POLL_VISIBLE_MS);
    expect(server.polls()).toHaveLength(4);
  });

  it("stops polling once every question has a termination reason", async () => {
    const { result } = await startRun(2);
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1"), endedQuestion("q-2")]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.status).toBe("idle");
    expect(result.current.resultsCompletion).toBe("settled");
    expect(result.current.terminalEvidence).toBe(true);
    expect(result.current.evidence?.closed).toBe(true);
    const polled = server.polls().length;
    await flush(RUN_POLL_VISIBLE_MS * 5);
    expect(server.polls()).toHaveLength(polled);
  });

  it("keeps polling through transient failures and recovers", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS * 2);
    expect(result.current.status).toBe("generating");
    expect(server.polls()).toHaveLength(2);

    server.dropConnection(false);
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.status).toBe("idle");
    expect(result.current.results).toHaveLength(1);
  });

  it("stops watching a run that disappears (404) and reports it", async () => {
    const { result } = await startRun();
    server.hideRun("run-1");
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBe(MESSAGES[useLangStore.getState().lang]["generate.run_not_found"]);
    const polled = server.polls().length;
    await flush(RUN_POLL_VISIBLE_MS * 3);
    expect(server.polls()).toHaveLength(polled);
  });

  it("gives up on questions that never end once the run status is terminal", async () => {
    const { result } = await startRun();
    server.setSnapshot("run-1", runSnapshot(
      [runningQuestion("q-1")],
      { status: "completed", completed_at: "2026-01-01T00:05:00+00:00" },
    ));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.status).toBe("generating");
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.status).toBe("idle");
    expect(result.current.resultsCompletion).toBe("unknown");
    expect(result.current.evidence?.questions["q-1"].processing).toBe("unknown");
  });
});

describe("useGenerate — progress and results from polled state", () => {
  it("shows per-question progress, then results as questions end (counts without double counting)", async () => {
    const { result } = await startRun(2);

    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1", "verify"), waitingQuestion("q-2")]));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.evidence?.questions["q-1"].processing).toBe("running");
    expect(result.current.evidence?.questions["q-2"].processing).toBe("waiting");
    expect(result.current.llmCalls).toEqual([
      expect.objectContaining({ type: "stage", agent: "verifier", stage: "verify", status: "start" }),
    ]);
    expect(result.current.displayResults).toHaveLength(0);

    // q-2 ends first (interleaved completion).
    const second = runSnapshot([runningQuestion("q-1", "verify"), endedQuestion("q-2")]);
    server.setSnapshot("run-1", second);
    await flush(RUN_POLL_VISIBLE_MS);
    expect(selectEndedCount(result.current.evidence!)).toBe(1);
    expect(selectFinalReceivedCount(result.current.evidence!)).toBe(1);
    expect(result.current.displayResults.map((d) => d.stableId)).toEqual(["q-2"]);
    expect(result.current.results).toHaveLength(1);

    // The very same snapshot polled again changes nothing.
    const before = result.current.evidence;
    await flush(RUN_POLL_VISIBLE_MS * 2);
    expect(result.current.evidence).toBe(before);
    expect(selectEndedCount(result.current.evidence!)).toBe(1);
    expect(result.current.displayResults).toHaveLength(1);

    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1"), endedQuestion("q-2")]));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(selectEndedCount(result.current.evidence!)).toBe(2);
    expect(selectFinalReceivedCount(result.current.evidence!)).toBe(2);
    expect(result.current.results).toHaveLength(2);
    expect(result.current.displayResults.map((d) => d.index)).toEqual([0, 1]);
    expect(result.current.llmCalls).toEqual([]);
    expect(result.current.finishedAt).toBe(Date.parse("2026-01-01T00:05:00+00:00"));
  });

  it("puts the verification trail persisted with a result on its card", async () => {
    const { result } = await startRun();
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
    const ended = endedQuestion("q-1");
    ended.result!.verification_trail = [passed];
    server.setSnapshot("run-1", runSnapshot([ended]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.displayResults[0].trail).toEqual([passed]);
    expect(result.current.evidence?.questions["q-1"].trail).toEqual([passed]);
  });

  it("carries stable id and content revision onto display results", async () => {
    const { result } = await startRun();
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1", { revision: 2 })]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.displayResults[0]).toMatchObject({
      stableId: "q-1",
      contentRevision: 2,
      isFinal: true,
    });
  });

  it("marks a failed question ended without a result", async () => {
    const { result } = await startRun();
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1", { reason: "failed" })]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.results).toHaveLength(0);
    expect(result.current.evidence?.questions["q-1"].terminal?.termination_reason).toBe("failed");
    expect(result.current.status).toBe("idle");
  });

  it("reports a failed run's error and settles completion as error", async () => {
    const { result } = await startRun();
    server.setSnapshot("run-1", runSnapshot(
      [endedQuestion("q-1", { reason: "failed" })],
      { status: "failed", error: "worker crashed" },
    ));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBe("worker crashed");
    expect(result.current.resultsCompletion).toBe("error");
    expect(result.current.terminalEvidence).toBe(false);
  });
});

describe("useGenerate — leaving the page never cancels the run (issue #908)", () => {
  it("unmount stops local polling and sends nothing to the server", async () => {
    const { unmount } = await startRun();
    await flush(RUN_POLL_VISIBLE_MS);
    const before = server.requests.length;

    unmount();
    await flush(RUN_POLL_VISIBLE_MS * 5);

    expect(server.requests).toHaveLength(before);
    expect(server.requests.every((r) => r.method === "GET" || r.url === "/api/generate")).toBe(true);
    expect(server.requests.filter((r) => r.method !== "GET")).toHaveLength(1);
  });

  it("reset stops polling locally without any server call", async () => {
    const { result } = await startRun();
    const before = server.requests.length;
    act(() => { result.current.reset(); });
    await flush(RUN_POLL_VISIBLE_MS * 3);

    expect(server.requests).toHaveLength(before);
    expect(result.current.status).toBe("idle");
    expect(result.current.evidence).toBeNull();
  });

  it("does not pass an abort signal to the submission or to polls", async () => {
    await startRun();
    await flush(RUN_POLL_VISIBLE_MS);
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    for (const call of fetchMock.mock.calls) {
      expect((call[1] as RequestInit | undefined)?.signal).toBeUndefined();
    }
  });
});

describe("useGenerate — resume a run by id (reopened page)", () => {
  it("shows the run still progressing, then its results", async () => {
    server.setSnapshot("run-1", runSnapshot([
      runningQuestion("q-1", "image"),
      waitingQuestion("q-2"),
    ]));
    const { result } = renderHook(() => useGenerate());
    let outcome!: Promise<unknown>;
    act(() => { outcome = result.current.resume("run-1"); });
    await flush();

    await expect(outcome).resolves.toEqual({ outcome: "resumed" });
    expect(result.current.status).toBe("generating");
    expect(result.current.runId).toBe("run-1");
    expect(result.current.evidence?.total).toBe(2);
    expect(result.current.evidence?.questions["q-1"].processing).toBe("running");
    expect(result.current.startedAt).toBe(Date.parse("2026-01-01T00:00:00+00:00"));
    expect(server.submits()).toHaveLength(0);

    // Results arrive while the reopened page keeps polling.
    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "arrived after reopen") }),
      endedQuestion("q-2"),
    ]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.status).toBe("idle");
    expect(result.current.results).toHaveLength(2);
    expect(result.current.displayResults[0].question.題目).toEqual(["arrived after reopen"]);
    expect(result.current.resultsCompletion).toBe("settled");
  });

  it("shows the results at once when the run already ended, and does not poll", async () => {
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.resume("run-1"); });
    await flush();

    expect(result.current.status).toBe("idle");
    expect(result.current.results).toHaveLength(1);
    expect(result.current.terminalEvidence).toBe(true);
    await flush(RUN_POLL_VISIBLE_MS * 3);
    expect(server.polls()).toHaveLength(1);
  });

  it("remounting after an unmount resumes the same run with no cancel in between", async () => {
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")]));
    const first = renderHook(() => useGenerate());
    act(() => { void first.result.current.resume("run-1"); });
    await flush();
    first.unmount();
    await flush(RUN_POLL_VISIBLE_MS * 2);
    const pollsWhileClosed = server.polls().length;

    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    const second = renderHook(() => useGenerate());
    act(() => { void second.result.current.resume("run-1"); });
    await flush();

    expect(server.polls().length).toBe(pollsWhileClosed + 1);
    expect(server.requests.every((r) => r.method === "GET")).toBe(true);
    expect(second.result.current.results).toHaveLength(1);
    expect(second.result.current.status).toBe("idle");
  });

  it("reports an unknown run as not_found, leaves nothing on screen and stops", async () => {
    server.hideRun("gone");
    const { result } = renderHook(() => useGenerate());
    let outcome!: Promise<unknown>;
    act(() => { outcome = result.current.resume("gone"); });
    await flush();

    await expect(outcome).resolves.toEqual({ outcome: "not_found" });
    expect(result.current.status).toBe("idle");
    expect(result.current.evidence).toBeNull();
    expect(result.current.runId).toBeNull();
    await flush(RUN_POLL_VISIBLE_MS * 3);
    expect(server.polls()).toHaveLength(1);
  });

  it("is idempotent for the run already being watched", async () => {
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")]));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.resume("run-1"); });
    await flush();
    await act(async () => { await result.current.resume("run-1"); });

    expect(server.polls()).toHaveLength(1);
  });

  it("retries a first read that failed transiently on the normal cadence", async () => {
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    server.dropConnection(true);
    const { result } = renderHook(() => useGenerate());
    let outcome!: Promise<unknown>;
    act(() => { outcome = result.current.resume("run-1"); });
    await flush();
    await expect(outcome).resolves.toEqual({ outcome: "resumed" });
    expect(result.current.status).toBe("generating");

    server.dropConnection(false);
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.status).toBe("idle");
    expect(result.current.results).toHaveLength(1);
  });
});

describe("useGenerate — generation log identity", () => {
  it("stores the run id from the acceptance, retains it through the end, and clears it on reset", async () => {
    const { result } = await startRun();
    expect(result.current.generationLogId).toBe("run-1");
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.generationLogId).toBe("run-1");

    act(() => { result.current.reset(); });
    expect(result.current.generationLogId).toBeNull();
    expect(result.current.runId).toBeNull();
  });

  it("ignores a late snapshot of the old run after reset", async () => {
    const { result } = await startRun();
    act(() => { result.current.reset(); });
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    await flush(RUN_POLL_VISIBLE_MS * 2);

    expect(result.current.evidence).toBeNull();
    expect(result.current.results).toHaveLength(0);
    expect(server.polls()).toHaveLength(0);
  });
});

describe("useGenerate — run timestamps", () => {
  it("records the run start and clears both timestamps on reset", async () => {
    const { result } = await startRun();
    expect(result.current.startedAt).toBe(1_000);
    expect(result.current.finishedAt).toBeNull();

    act(() => { result.current.reset(); });
    expect(result.current.startedAt).toBeNull();
    expect(result.current.finishedAt).toBeNull();
  });

  it("records the finish time when the submission fails", async () => {
    vi.setSystemTime(8_000);
    server.failSubmit(500, {});
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.finishedAt).toBe(8_000);
  });
});

describe("admission", () => {
  it("waits for the 202 acceptance and resolves the admission promise", async () => {
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")]));
    const { result } = renderHook(() => useGenerate());
    expect(result.current.admission).toBe("idle");
    expect(result.current.admissionError).toBeNull();
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    expect(result.current.admission).toBe("submitting");
    expect(result.current.status).toBe("generating");
    await flush();
    await expect(promise).resolves.toEqual({ outcome: "admitted", runId: "run-1" });
    expect(result.current.admission).toBe("admitted");

    act(() => { result.current.reset(); });
    expect(result.current.admission).toBe("idle");
    expect(result.current.admissionError).toBeNull();
  });

  it.each([
    [401, "", "Session expired — please sign in again"],
    [422, JSON.stringify({ detail: [{ field: "grade", code: "unresolved" }] }), "Incomplete request: grade (unresolved)"],
    [500, "not JSON", "Submit failed: HTTP 500"],
  ])("rejects HTTP %s with the existing error message", async (status, body, reason) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status })));
    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toBe(result.current.errorMessage);
    await expect(promise).resolves.toEqual({ outcome: "rejected", reason });
    expect(result.current.finishedAt).not.toBeNull();
  });

  it("handles a transport failure as a rejection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("connection lost"); }));
    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    act(() => { promise = result.current.generate({ subject: "math" }); });
    await flush();

    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toBe("connection lost");
    await expect(promise).resolves.toEqual({ outcome: "rejected", reason: "connection lost" });
  });

  it("ignores a duplicate run and keeps the active one", async () => {
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")]));
    const { result } = renderHook(() => useGenerate());
    let first!: Promise<AdmissionOutcome>;
    act(() => { first = result.current.generate({ subject: "math" }); });
    let duplicate!: Promise<AdmissionOutcome>;
    act(() => { duplicate = result.current.generate({ subject: "math" }); });
    await expect(duplicate).resolves.toEqual({
      outcome: "rejected",
      reason: "generation already in progress",
    });
    await flush();
    expect(server.submits()).toHaveLength(1);
    expect(result.current.admission).toBe("admitted");
    expect(result.current.admissionError).toBeNull();
    await expect(first).resolves.toEqual({ outcome: "admitted", runId: "run-1" });
  });

  it("settles a pending admission on reset and unmount", async () => {
    const { result, unmount } = renderHook(() => useGenerate());
    let pending!: Promise<AdmissionOutcome>;
    act(() => { pending = result.current.generate({ subject: "math" }); });
    act(() => { result.current.reset(); });
    await expect(pending).resolves.toEqual({ outcome: "rejected", reason: "reset" });
    await flush();
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

  it.each(["settled", "error", "unknown"] as const)("restores %s completion through the snapshot adapter", async (completion) => {
    const { result } = await startRun();
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1", "text")]));
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.llmCalls).not.toHaveLength(0);
    // The restore is only allowed once the observed run is over.
    act(() => { result.current.reset(); });
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

  it("refuses restoration while a run is being watched, without changing state", async () => {
    const { result } = await startRun();
    const before = result.current;
    act(() => { expect(result.current.restoreResults(snapshot)).toBe(false); });
    expect(result.current).toBe(before);
  });
});

describe("workspace operation", () => {
  const originalBeginOperation = useWorkspaceStore.getState().beginOperation;
  beforeEach(() => { resetWorkspaceStoreForTests(); });
  afterEach(() => {
    useWorkspaceStore.setState({ beginOperation: originalBeginOperation });
  });

  function spyOnEnd() {
    const begin = useWorkspaceStore.getState().beginOperation;
    const end = vi.fn();
    vi.spyOn(useWorkspaceStore.getState(), "beginOperation").mockImplementation((...args) => {
      const handle = begin(...args);
      return { id: handle.id, end: (value) => { end(value); handle.end(value); } };
    });
    return end;
  }

  it("holds a generation operation while the run is watched and ends it completed", async () => {
    const end = spyOnEnd();
    const { result } = await startRun();
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ kind: "generation", surface: "generate.results" }),
    ]);
    server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1")]));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(end).toHaveBeenCalledWith("completed");
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
    expect(result.current.status).toBe("idle");
  });

  it("ends the operation failed when the server reports the run failed", async () => {
    const end = spyOnEnd();
    await startRun();
    server.setSnapshot("run-1", runSnapshot(
      [endedQuestion("q-1", { reason: "failed" })],
      { status: "failed", error: "boom" },
    ));
    await flush(RUN_POLL_VISIBLE_MS);

    expect(end).toHaveBeenCalledWith("failed");
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
  });

  it("ends the operation failed when the submission is rejected", async () => {
    const end = spyOnEnd();
    server.failSubmit(500, {});
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate({ subject: "math" }); });
    await flush();

    expect(end).toHaveBeenCalledWith("failed");
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
  });

  it.each(["reset", "unmount"] as const)("ends generation on %s as aborted (local bookkeeping only)", async (how) => {
    const end = spyOnEnd();
    const { result, unmount } = await startRun();
    if (how === "reset") act(() => { result.current.reset(); });
    else unmount();

    expect(end).toHaveBeenCalledWith("aborted");
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
    unmount();
  });
});

describe("cadence constants", () => {
  it("polls about every 3 s visible and slower (15 s) hidden", () => {
    expect(RUN_POLL_VISIBLE_MS).toBe(3_000);
    expect(RUN_POLL_HIDDEN_MS).toBe(15_000);
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


// ---------------------------------------------------------------------------
// issue #946 — parseErrorPayload (task 6.1)
// ---------------------------------------------------------------------------

describe("useGenerate — parseErrorPayload (issue #946)", () => {
  it("extracts failure_class when it is a recognized taxonomy code", () => {
    const raw = JSON.stringify({
      code: "generation_failed",
      message: "backend message",
      failure_class: "rate_limited",
    });
    const result = parseErrorPayload(raw);
    expect(result.failureClass).toBe("rate_limited");
    expect(result.message).toBe("backend message");
  });

  it("returns failureClass=null when failure_class is absent", () => {
    const raw = JSON.stringify({ code: "generation_failed", message: "some error" });
    const result = parseErrorPayload(raw);
    expect(result.failureClass).toBeNull();
    expect(result.message).toBe("some error");
  });

  it("returns failureClass=null when failure_class is an unrecognized string", () => {
    const raw = JSON.stringify({ message: "err", failure_class: "not_a_real_code" });
    const result = parseErrorPayload(raw);
    expect(result.failureClass).toBeNull();
  });

  it("falls back to raw string as message when not JSON", () => {
    const raw = "plain error text";
    const result = parseErrorPayload(raw);
    expect(result.failureClass).toBeNull();
    expect(result.message).toBe("plain error text");
  });

  it("handles empty string", () => {
    const result = parseErrorPayload("");
    expect(result.failureClass).toBeNull();
    expect(result.message).toBe("Unknown error");
  });

  it("recognizes all 10 taxonomy codes", () => {
    const codes = [
      "auth_config", "quota_billing_exhausted", "rate_limited", "overloaded",
      "timeout", "connection", "context_length", "content_filtered",
      "malformed_response", "unknown",
    ];
    for (const code of codes) {
      const raw = JSON.stringify({ message: "err", failure_class: code });
      const result = parseErrorPayload(raw);
      expect(result.failureClass).toBe(code);
    }
  });
});

// ---------------------------------------------------------------------------
// issue #946 — case "error" localization (task 6.2/6.3)
// ---------------------------------------------------------------------------

describe("useGenerate — case 'error' localization (issue #946)", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockClear();
    // Default: open stream and stay open (no events until test delivers them)
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
    });
  });

  it("localizes errorMessage when failure_class is a recognized code (en-US)", async () => {
    const originalLang = useLangStore.getState().lang;
    useLangStore.getState().setLang("en-US");
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });
    try {
      const { result } = await startRun(1, runSnapshot(
        [waitingQuestion("q-1")], { live_events_available: true },
      ));
      await flush(RUN_POLL_VISIBLE_MS + 10);
      await flush(); // let fetchEventSource settle

      // Real wire shape: full v2 envelope with payload containing failure fields.
      // Run-level error has no context.question_id.
      await act(async () => {
        capturedOnMessage?.({
          event: "error",
          data: JSON.stringify({
            event: "error",
            payload: {
              code: "stream_failed",
              message: "Rate limited by provider",
              failure_class: "rate_limited",
            },
          }),
        });
        for (let i = 0; i < 5; i++) await Promise.resolve();
      });

      expect(result.current.status).toBe("error");
      expect(result.current.errorFailureClass).toBe("rate_limited");
      // Must contain the localized label (not the raw backend string)
      expect(result.current.errorMessage).toContain("Rate limited");
      expect(result.current.errorMessage).not.toBe("Rate limited by provider");
    } finally {
      useLangStore.getState().setLang(originalLang);
    }
  });

  it("falls back to raw message when failure_class is absent", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")], { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();

    // Real wire shape: run-level error with no context and no failure_class in payload
    await act(async () => {
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          payload: {
            code: "stream_failed",
            message: "Raw backend error text",
          },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorFailureClass).toBeNull();
    expect(result.current.errorMessage).toBe("Raw backend error text");
  });

  it("preserves draft content already received when error event arrives (#938)", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")], { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();

    // Deliver a v2 result event (draft) via the live stream
    const resultEvent = {
      event: "result",
      data: JSON.stringify({
        event: "result",
        context: { run_id: "run-1", question_id: "q-1", event_seq: 2, content_revision: 1 },
        payload: {
          id: "q-1",
          情境: ["個人"],
          題型種類: "單一題",
          題型: "選擇題",
          題目: ["Draft question text"],
          正確解題分析: ["answer"],
        },
      }),
    };

    await act(async () => {
      capturedOnMessage?.(resultEvent);
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Sanity: at least one result visible before error
    expect(result.current.results.length).toBeGreaterThan(0);

    // Now a run-level error event arrives (real wire shape: envelope with payload)
    await act(async () => {
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          payload: {
            code: "stream_failed",
            message: "Connection lost",
            failure_class: "connection",
          },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Status is error
    expect(result.current.status).toBe("error");
    // Content received before the error must STILL be visible (#938 requirement)
    expect(result.current.results.length).toBeGreaterThan(0);
    expect(result.current.errorMessage).toBeTruthy();
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

describe("useGenerate — pollReadFailed (issue #909)", () => {
  it("pollReadFailed is false after 1 dropped connection", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.pollReadFailed).toBe(false);
  });

  it("pollReadFailed is false after 2 dropped connections", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.pollReadFailed).toBe(false);
  });

  it("pollReadFailed is true after 3 dropped connections", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.pollReadFailed).toBe(true);
  });

  it("after 3 failed polls, no-terminal questions are unknown; exactly one POST was sent", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);

    expect(result.current.pollReadFailed).toBe(true);
    // Questions with no terminal → processing becomes unknown
    expect(result.current.evidence?.questions["q-1"].processing).toBe("unknown");
    // No re-submit on poll failure — generation keeps running on server
    expect(server.submits()).toHaveLength(1);
  });

  it("subsequent successful poll clears pollReadFailed and restores processing from snapshot", async () => {
    const { result } = await startRun();
    server.dropConnection(true);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);
    await flush(RUN_POLL_VISIBLE_MS);
    expect(result.current.pollReadFailed).toBe(true);
    expect(result.current.evidence?.questions["q-1"].processing).toBe("unknown");

    // Restore server with running snapshot
    server.dropConnection(false);
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1", "text")]));
    await flush(RUN_POLL_VISIBLE_MS);

    // Flag cleared; processing restored to "running" from snapshot
    expect(result.current.pollReadFailed).toBe(false);
    expect(result.current.evidence?.questions["q-1"].processing).toBe("running");
  });
});

// ---------------------------------------------------------------------------
// Live SSE consumer tests (issue #909)
// ---------------------------------------------------------------------------

describe("useGenerate — live events (issue #909)", () => {
  /** Helpers to build SSE event wire format (full {event, context, payload} envelope). */
  function sseEnvelope(
    name: string,
    payload: unknown,
    questionId: string,
    seq: number,
    runId = "run-1",
    extraContext: Record<string, unknown> = {},
  ): { event: string; data: string } {
    return {
      event: name,
      data: JSON.stringify({
        event: name,
        context: { run_id: runId, question_id: questionId, event_seq: seq, ...extraContext },
        payload,
      }),
    };
  }

  function terminalEnvelope(questionId: string, seq: number, runId = "run-1") {
    return sseEnvelope(
      "question_terminal",
      {
        termination_reason: "normal",
        has_final: true,
        final_revision: 1,
        delivery_status: "complete",
        expected: [], delivered: [], missing: [],
        review: { status: "passed", content_revision: 1 },
      },
      questionId,
      seq,
      runId,
    );
  }

  function resultEnvelope(questionId: string, seq: number, contentRevision = 1, runId = "run-1") {
    return sseEnvelope(
      "result",
      {
        id: questionId,
        情境: [],
        題型種類: "single",
        題型: "multiple_choice",
        題目: [`text ${questionId}`],
        正確解題分析: ["a"],
      },
      questionId,
      seq,
      runId,
      { content_revision: contentRevision },
    );
  }

  beforeEach(() => {
    fetchEventSourceMock.mockClear();
    // Default: simulate a connection that stays open (no events, no close)
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      // Stream stays open until aborted via opts.signal
    });
  });

  it("T1: stream not opened when snapshot does not advertise live_events_available", async () => {
    // Default snapshot: no live_events_available
    await startRun(1);
    await flush(RUN_POLL_VISIBLE_MS + 10);
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
  });

  it("T2: stream opened exactly once when advertised; live question_terminal updates evidence before next poll", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    // Pass the live-events snapshot directly to startRun
    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    // Advance timer to trigger first poll which sees live_events_available
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush(); // let the async fetchEventSource call settle

    // Stream should be opened exactly once
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
    expect(fetchEventSourceMock.mock.calls[0][0]).toMatch(/\/api\/runs\/run-1\/events/);

    // Verify auth headers (X-Frontend-Build-ID)
    const callOpts = fetchEventSourceMock.mock.calls[0][1] as { headers?: Record<string, string> };
    const headers = callOpts.headers ?? {};
    const buildId = headers["X-Frontend-Build-ID"] ?? headers["x-frontend-build-id"];
    expect(buildId).toBe("test-build-id");

    // Deliver live result + terminal events through the captured onmessage
    await act(async () => {
      capturedOnMessage?.(resultEnvelope("q-1", 2));
      capturedOnMessage?.(terminalEnvelope("q-1", 3));
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Evidence updated: q-1 should now have a final result
    expect(result.current.evidence?.questions["q-1"].content.receipt).toBe("final");

    // Second poll: snapshot still running; verify stream NOT reopened (liveRunIdRef is still set)
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")], { live_events_available: true }));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
  });

  it("T3: started event with different run_id closes stream without changing evidence", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    let capturedSignal: AbortSignal | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      capturedSignal = opts.signal;
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    const evidenceBefore = result.current.evidence;

    // Deliver a "started" event with a DIFFERENT run_id
    const wrongStartedEvent = {
      event: "started",
      data: JSON.stringify({
        event: "started",
        context: { run_id: "run-WRONG", event_seq: 1 },
        payload: {
          protocol_version: 2,
          total: 1,
          questions: [{ index: 0, question_id: "q-1" }],
        },
      }),
    };
    await act(async () => {
      capturedOnMessage?.(wrongStartedEvent);
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Stream should be aborted
    expect(capturedSignal?.aborted).toBe(true);
    // Evidence unchanged
    expect(result.current.evidence).toBe(evidenceBefore);
  });

  it("T4: stream error falls back silently; no error state, polling continues, no question becomes unknown", async () => {
    let capturedOnError: ((err: unknown) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnError = opts.onerror;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    // Simulate a stream error (onerror re-throws to prevent retry)
    await act(async () => {
      try { capturedOnError?.(new Error("connection lost")); } catch { /* expected re-throw */ }
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // No error status surfaced
    expect(result.current.status).toBe("generating");
    expect(result.current.errorMessage).toBeNull();
    // No question should be "unknown" from stream loss
    expect(result.current.evidence?.questions["q-1"].processing).not.toBe("unknown");
    // Polling still continuing
    const pollsBefore = server.polls().length;
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")], { live_events_available: false }));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    expect(server.polls().length).toBeGreaterThan(pollsBefore);
  });

  it("T5: later snapshot recording same outcome as live events leaves ended/final counts unchanged", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    // Deliver result + terminal via live stream
    await act(async () => {
      capturedOnMessage?.(resultEnvelope("q-1", 2));
      capturedOnMessage?.(terminalEnvelope("q-1", 3));
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Count after live events
    const endedAfterLive = selectEndedCount(result.current.evidence!);
    const finalAfterLive = selectFinalReceivedCount(result.current.evidence!);
    expect(endedAfterLive).toBe(1);
    expect(finalAfterLive).toBe(1);

    // Now snapshot delivers the same outcome
    server.setSnapshot("run-1", runSnapshot(
      [endedQuestion("q-1", { question: examQuestion("q-1") })],
      { live_events_available: false, status: "completed" },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);

    // Counts unchanged (snapshot is idempotent)
    expect(selectEndedCount(result.current.evidence!)).toBe(endedAfterLive);
    expect(selectFinalReceivedCount(result.current.evidence!)).toBe(finalAfterLive);
  });

  it("T6: unmount aborts stream controller; no cancel request sent; no second POST /api/generate", async () => {
    let capturedSignal: AbortSignal | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      capturedSignal = opts.signal;
      await opts.onopen?.(new Response(null, { status: 200 }));
      // Stream stays open until signalled
    });

    const { unmount } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    const submitsBefore = server.submits().length;

    // Unmount the hook — stopWatching should abort only the AbortController
    act(() => { unmount(); });
    await flush();

    // AbortController aborted
    expect(capturedSignal?.aborted).toBe(true);
    // No cancel requests sent
    const cancelRequests = server.requests.filter(
      (r) => r.url.includes("cancel") || r.method === "DELETE",
    );
    expect(cancelRequests).toHaveLength(0);
    // No second POST /api/generate
    expect(server.submits().length).toBe(submitsBefore);
  });

  it("T3b: started with a different manifest closes the stream without changing evidence", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    let capturedSignal: AbortSignal | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      capturedSignal = opts.signal;
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    const evidenceBefore = result.current.evidence;

    // Deliver a "started" event with matching run_id but different total/questions
    const mismatchedManifestEvent = {
      event: "started",
      data: JSON.stringify({
        event: "started",
        context: { run_id: "run-1", event_seq: 1 },
        payload: {
          protocol_version: 3,
          total: 99, // mismatched total
          questions: [{ index: 0, question_id: "q-DIFFERENT" }],
        },
      }),
    };
    await act(async () => {
      capturedOnMessage?.(mismatchedManifestEvent);
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Stream should be aborted due to manifest mismatch
    expect(capturedSignal?.aborted).toBe(true);
    // Evidence unchanged
    expect(result.current.evidence).toBe(evidenceBefore);
  });

  it("T7: done closes the stream and it is not reopened by the library", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    let capturedSignal: AbortSignal | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      capturedSignal = opts.signal;
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    const { result } = await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
    expect(capturedSignal?.aborted).toBe(false);

    // Send done event
    await act(async () => {
      capturedOnMessage?.({ event: "done", data: "" });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Signal aborted after done
    expect(capturedSignal?.aborted).toBe(true);
    // No error surfaced
    expect(result.current.status).toBe("generating");
    expect(result.current.errorMessage).toBeNull();
  });

  it("T8: after a stream error the stream is not reopened on later polls", async () => {
    let capturedOnError: ((err: unknown) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnError = opts.onerror;
    });

    await startRun(1, runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);

    // Simulate a stream error
    await act(async () => {
      try { capturedOnError?.(new Error("network loss")); } catch { /* expected re-throw */ }
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Subsequent polls still advertise live_events_available — stream must NOT reopen
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")], { live_events_available: true }));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")], { live_events_available: true }));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")], { live_events_available: true }));
    await flush(RUN_POLL_VISIBLE_MS + 10);

    // fetchEventSource was called exactly once despite multiple polls advertising live_events_available
    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
  });

  it("T9: a resumed run seeds the decoder from the snapshot and applies a live question_terminal", async () => {
    let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });

    // Resume a run that advertises live events
    server.setSnapshot("run-1", runSnapshot(
      [waitingQuestion("q-1")],
      { live_events_available: true },
    ));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.resume("run-1"); });
    await flush();
    // The first poll from resume opens the stream
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush();

    expect(fetchEventSourceMock).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("generating");

    // Deliver a live question_terminal for q-1
    await act(async () => {
      capturedOnMessage?.(terminalEnvelope("q-1", 2));
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Evidence updated: q-1 should now be ended
    expect(result.current.evidence?.questions["q-1"].processing).toBe("ended");
  });
});
