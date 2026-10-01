/**
 * useGenerate — issue #912 admission features.
 *
 * 1. Submission key: generated once per generate() call, sent in the POST body,
 *    reused on retry after a network error, cleared after any server response.
 * 2. 429 queue-limit: shows a readable error, keeps form usable (status "error",
 *    NOT "generating"), no auto-resubmit.
 * 3. Queue position: exposed via queuePosition, updated from snapshot.queue_position.
 * 4. Frontend fakeRunServer: queue position from snapshot → queuePosition state.
 *
 * NOTE: All tests use vi.useFakeTimers().  waitFor() is NOT used here because
 * waitFor's internal polling relies on real setTimeout, which fake timers
 * intercept.  Instead every test uses flush() (which calls
 * vi.advanceTimersByTimeAsync) to drain microtasks and synthetic timers.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@sentry/react", () => ({ captureException: vi.fn() }));
vi.mock("../sentry", () => ({ isSentryEnabled: vi.fn().mockReturnValue(false) }));

import { useGenerate } from "./useGenerate";
import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import { MESSAGES } from "../i18n/messages";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import { acceptedRun, waitingQuestion, runSnapshot } from "../test/runFixtures";

const MINIMAL_PARAMS = {
  subject: "math",
  count: 1,
  seed: 41,
  grade: 8,
  context: ["個人"] as string[],
  set_type: "單一題",
  q_type: ["選擇題"] as string[],
  style: ["text_only"] as string[],
  math_thinking: ["形成"] as string[],
  learning_content: ["A-7-7"],
  learning_performance: ["s-IV-12"],
  core_competency: ["數-J-A2"],
  content_type: "純文字",
  skip_verify: true,
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  server = installFakeRunServer();
  useAuthStore.setState({ token: "tok", user: { id: "u912", email: "u912@test.com", created_at: "2024-01-01T00:00:00Z" } });
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/**
 * Drain pending microtasks and advance fake timers by `ms`.
 * Must be called inside act() or as an awaited expression at the top level
 * of an async test.
 */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i++) await Promise.resolve();
  });
}

// ---------------------------------------------------------------------------
// Submission key lifecycle
// ---------------------------------------------------------------------------

describe("submission key", () => {
  it("sends a UUID submission_key in the POST body", async () => {
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")], { status: "running" }));
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);

    const submit = server.submits()[0];
    const body = submit?.body as Record<string, unknown> | undefined;
    expect(body?.submission_key).toMatch(UUID_RE);
  });

  it("reuses the same key on network-error retry", async () => {
    // First call: submission-level network error (fetch throws TypeError).
    // dropSubmitConnection() makes POST /api/generate throw — unlike
    // dropConnection() which only fails GET polling.
    server.dropSubmitConnection(true);
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);
    expect(result.current.status).toBe("error");

    const firstKey = (server.submits()[0]?.body as Record<string, unknown>)?.submission_key;
    expect(firstKey).toMatch(UUID_RE);

    // Restore the connection and retry.
    server.dropSubmitConnection(false);
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")], { status: "running" }));
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);

    const secondKey = (server.submits()[1]?.body as Record<string, unknown>)?.submission_key;
    expect(secondKey).toBe(firstKey);
  });

  it("generates a new key after a 202 success", async () => {
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")], { status: "running" }));
    const { result } = renderHook(() => useGenerate());

    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(200);
    const key1 = (server.submits()[0]?.body as Record<string, unknown>)?.submission_key as string;
    expect(key1).toMatch(UUID_RE);

    // Reset and generate again.
    act(() => result.current.reset());
    server.setAcceptance(acceptedRun(1, "run-2"));
    server.setSnapshot("run-2", runSnapshot([waitingQuestion("q-1", 0)], { run_id: "run-2", status: "running" }));
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(200);
    const key2 = (server.submits()[1]?.body as Record<string, unknown>)?.submission_key as string;
    expect(key2).toMatch(UUID_RE);
    expect(key2).not.toBe(key1);
  });

  it("generates a new key after a 4xx error (not network error)", async () => {
    server.failSubmit(422, { detail: "bad request" });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(200);
    expect(result.current.status).toBe("error");

    const key1 = (server.submits()[0]?.body as Record<string, unknown>)?.submission_key as string;

    // Recover and generate again.
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")], { status: "running" }));
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(200);
    const key2 = (server.submits()[1]?.body as Record<string, unknown>)?.submission_key as string;
    expect(key2).toMatch(UUID_RE);
    expect(key2).not.toBe(key1);
  });
});

// ---------------------------------------------------------------------------
// 429 queue limit
// ---------------------------------------------------------------------------

describe("429 queue limit", () => {
  it("shows the LOCALIZED message (en-US) and NOT the server detail string", async () => {
    useLangStore.setState({ lang: "en-US" });
    server.failSubmit(429, {
      code: "queue_limit_reached",
      detail: "server detail",
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);

    expect(result.current.status).toBe("error");
    // Must show the localized i18n string, not the raw server detail
    expect(result.current.errorMessage).toBe(MESSAGES["en-US"]["generate.queue_limit"]);
    expect(result.current.errorMessage).not.toContain("server detail");
    // No run was started
    expect(result.current.runId).toBeNull();
  });

  it("shows the LOCALIZED message (zh-TW) and NOT the server detail string", async () => {
    useLangStore.setState({ lang: "zh-TW" });
    server.failSubmit(429, {
      code: "queue_limit_reached",
      detail: "server detail",
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toBe(MESSAGES["zh-TW"]["generate.queue_limit"]);
    expect(result.current.errorMessage).not.toContain("server detail");
    expect(result.current.runId).toBeNull();
  });

  it("shows the server detail as fallback when 429 code is absent/unknown", async () => {
    server.failSubmit(429, {
      detail: "server detail",
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);

    expect(result.current.status).toBe("error");
    // No known errorCode → falls back to server's detail
    expect(result.current.errorMessage).toContain("server detail");
    expect(result.current.runId).toBeNull();
  });

  it("shows the error message and keeps form usable (status=error not generating)", async () => {
    server.failSubmit(429, {
      code: "queue_limit_reached",
      detail: "server detail",
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    // flush enough microtasks for the async response.json() and setState to complete
    await flush(50);

    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).not.toContain("server detail");
    // No run was started
    expect(result.current.runId).toBeNull();
  });

  it("generates a new key after a 429 (new intent required)", async () => {
    server.failSubmit(429, {
      code: "queue_limit_reached",
      detail: "queue full",
    });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);
    expect(result.current.status).toBe("error");

    const key1 = (server.submits()[0]?.body as Record<string, unknown>)?.submission_key as string;
    expect(key1).toMatch(UUID_RE);

    // Try again (after some wait, queue may have cleared)
    server.setSnapshot("run-1", runSnapshot([waitingQuestion("q-1")], { status: "running" }));
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(200);

    const key2 = (server.submits()[1]?.body as Record<string, unknown>)?.submission_key as string;
    expect(key2).toMatch(UUID_RE);
    expect(key2).not.toBe(key1);
  });

  it("does NOT auto-resubmit after 429", async () => {
    server.failSubmit(429, { code: "queue_limit_reached", detail: "queue full" });
    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(50);
    expect(result.current.status).toBe("error");

    // Wait a bit to confirm no polling/retry happens automatically
    await flush(5000);
    expect(server.submits()).toHaveLength(1);
    expect(server.polls()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Queue position from snapshot
// ---------------------------------------------------------------------------

describe("queue position", () => {
  it("exposes queuePosition from snapshot.queue_position", async () => {
    const snap = runSnapshot([waitingQuestion("q-1")], {
      status: "queued",
      queue_position: 2,
    });
    server.setSnapshot("run-1", snap);

    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    // Wait for admission (202 received and run started)
    await flush(100);
    expect(result.current.status).toBe("generating");
    // Advance past first poll interval (3000 ms) so the snapshot is applied
    await flush(3200);

    expect(result.current.queuePosition).toBe(2);
  });

  it("queuePosition is null when not queued", async () => {
    const snap = runSnapshot([waitingQuestion("q-1")], { status: "running" });
    server.setSnapshot("run-1", snap);

    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(100);
    expect(result.current.status).toBe("generating");
    await flush(3200);

    expect(result.current.queuePosition).toBeNull();
  });

  it("queuePosition is cleared on reset", async () => {
    const snap = runSnapshot([waitingQuestion("q-1")], {
      status: "queued",
      queue_position: 1,
    });
    server.setSnapshot("run-1", snap);

    const { result } = renderHook(() => useGenerate());
    act(() => { void result.current.generate(MINIMAL_PARAMS); });
    await flush(100);
    expect(result.current.status).toBe("generating");
    await flush(3200);
    expect(result.current.queuePosition).toBe(1);

    act(() => result.current.reset());
    expect(result.current.queuePosition).toBeNull();
  });
});
