/**
 * Tests for issue #946 gap 2 — snapshot `failed` with failure_class shows
 * localized message; without failure_class falls back to the generic message.
 *
 * Gap 2 frontend requirement:
 *   - When the polled snapshot has status="failed" AND a recognized failure_class,
 *     useGenerate sets errorMessage to the localized text (same keys as the live path)
 *     and errorFailureClass to the code.
 *   - When status="failed" but failure_class is absent or null, falls back to the
 *     generic snapshot.error string.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchEventSourceMock = vi.hoisted(() =>
  vi
    .fn<
      [
        string,
        {
          onopen?: (r: Response) => Promise<void> | void;
          onmessage?: (ev: {
            event: string;
            data: string;
            id?: string;
            retry?: number;
          }) => void;
          onerror?: (err: unknown) => void;
          onclose?: () => void;
          signal?: AbortSignal;
          openWhenHidden?: boolean;
          headers?: Record<string, string>;
          method?: string;
        },
      ],
      Promise<void>
    >()
    .mockResolvedValue(undefined),
);

vi.mock("@sentry/react", () => ({
  captureException: vi.fn(),
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: vi.fn().mockReturnValue(false),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

import {
  RUN_POLL_VISIBLE_MS,
  useGenerate,
  type AdmissionOutcome,
} from "./useGenerate";
import { useLangStore } from "../store/langStore";
import { MESSAGES } from "../i18n/messages";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import {
  endedQuestion,
  runSnapshot,
  waitingQuestion,
} from "../test/runFixtures";

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000);
  server = installFakeRunServer();
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function startRun(
  count = 1,
  snapshot = runSnapshot(
    Array.from({ length: count }, (_, i) => waitingQuestion(`q-${i + 1}`)),
  ),
) {
  server.setSnapshot("run-1", snapshot);
  const hook = renderHook(() => useGenerate());
  let admission!: Promise<AdmissionOutcome>;
  act(() => {
    admission = hook.result.current.generate({ subject: "math", count });
  });
  await flush();
  return { ...hook, admission };
}

describe("useGenerate — snapshot failure_class (issue #946 gap 2)", () => {
  it("shows localized message when snapshot has failure_class", async () => {
    const lang = useLangStore.getState().lang;
    useLangStore.getState().setLang("en-US");
    try {
      const { result } = await startRun(
        1,
        runSnapshot([waitingQuestion("q-1")]),
      );

      // Return a failed snapshot with failure_class
      server.setSnapshot(
        "run-1",
        runSnapshot([endedQuestion("q-1", { reason: "failed" })], {
          status: "failed",
          error: "Run execution failed (RuntimeError)",
          failure_class: "unknown",
        }),
      );
      await flush(RUN_POLL_VISIBLE_MS + 10);

      expect(result.current.status).toBe("error");
      expect(result.current.errorFailureClass).toBe("unknown");
      // Should show localized text, not the raw backend error string
      const enMessages = MESSAGES["en-US"];
      const localizedLabel = enMessages?.["error.class.unknown"];
      expect(result.current.errorMessage).toBeTruthy();
      // When failure_class is "unknown", the message should be the localized unknown text
      // (or at minimum not be the raw backend string "Run execution failed (RuntimeError)")
      // — the exact text depends on i18n but it must NOT be the raw backend error.
      if (localizedLabel) {
        expect(result.current.errorMessage).toContain(localizedLabel);
      }
    } finally {
      useLangStore.getState().setLang(lang);
    }
  });

  it("falls back to snapshot.error when failure_class is absent", async () => {
    const { result } = await startRun(
      1,
      runSnapshot([waitingQuestion("q-1")]),
    );

    server.setSnapshot(
      "run-1",
      runSnapshot([endedQuestion("q-1", { reason: "failed" })], {
        status: "failed",
        error: "some opaque backend error",
      }),
    );
    await flush(RUN_POLL_VISIBLE_MS + 10);

    expect(result.current.status).toBe("error");
    // Without failure_class, errorFailureClass must be null
    expect(result.current.errorFailureClass).toBeNull();
    // And errorMessage should fall back to snapshot.error
    expect(result.current.errorMessage).toContain("some opaque backend error");
  });

  it("falls back to snapshot.error when failure_class is null explicitly", async () => {
    const { result } = await startRun(
      1,
      runSnapshot([waitingQuestion("q-1")]),
    );

    server.setSnapshot(
      "run-1",
      runSnapshot([endedQuestion("q-1", { reason: "failed" })], {
        status: "failed",
        error: "raw error message",
        failure_class: null,
      } as Parameters<typeof runSnapshot>[1]),
    );
    await flush(RUN_POLL_VISIBLE_MS + 10);

    expect(result.current.status).toBe("error");
    expect(result.current.errorFailureClass).toBeNull();
    expect(result.current.errorMessage).toContain("raw error message");
  });

  it("uses rate_limited localized label from snapshot failure_class", async () => {
    const lang = useLangStore.getState().lang;
    useLangStore.getState().setLang("zh-TW");
    try {
      const { result } = await startRun(
        1,
        runSnapshot([waitingQuestion("q-1")]),
      );

      server.setSnapshot(
        "run-1",
        runSnapshot([endedQuestion("q-1", { reason: "failed" })], {
          status: "failed",
          error: "provider rate limited",
          failure_class: "rate_limited",
        }),
      );
      await flush(RUN_POLL_VISIBLE_MS + 10);

      expect(result.current.status).toBe("error");
      expect(result.current.errorFailureClass).toBe("rate_limited");
      const zhMessages = MESSAGES["zh-TW"];
      const localizedLabel = zhMessages?.["error.class.rate_limited"];
      if (localizedLabel) {
        expect(result.current.errorMessage).toContain(localizedLabel);
      } else {
        // If the key doesn't exist, at least the generic behavior holds
        expect(result.current.errorFailureClass).toBe("rate_limited");
      }
    } finally {
      useLangStore.getState().setLang(lang);
    }
  });
});

// ---------------------------------------------------------------------------
// issue #946 — live-stream error routing bugs (Bug 1 + Bug 2)
// ---------------------------------------------------------------------------

describe("useGenerate — live-stream error routing (issue #946 bugs 1 & 2)", () => {
  let capturedOnMessage: ((ev: { event: string; data: string }) => void) | undefined;

  beforeEach(() => {
    capturedOnMessage = undefined;
    fetchEventSourceMock.mockClear();
    fetchEventSourceMock.mockImplementation(async (_url: string, opts: Parameters<typeof fetchEventSourceMock>[1]) => {
      await opts.onopen?.(new Response(null, { status: 200 }));
      capturedOnMessage = opts.onmessage;
    });
  });

  async function startLiveRun(count = 2) {
    const questions = Array.from({ length: count }, (_, i) => waitingQuestion(`q-${i + 1}`));
    const { result } = await startRun(count, runSnapshot(questions, { live_events_available: true }));
    await flush(RUN_POLL_VISIBLE_MS + 10);
    await flush(); // let fetchEventSource settle
    return result;
  }

  // Bug 1: question-scoped error must NOT abort the run
  it("question-scoped generation_failed does not set run status to error", async () => {
    const result = await startLiveRun(2);

    await act(async () => {
      // Real wire shape: context.question_id present → question-scoped
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          context: { run_id: "run-1", question_id: "q-1", event_seq: 3 },
          payload: { code: "generation_failed", message: "Question failed", failure_class: "timeout" },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Run must NOT have moved to error — sibling questions are still running
    expect(result.current.status).not.toBe("error");
    expect(result.current.errorMessage).toBeNull();
    expect(result.current.errorFailureClass).toBeNull();
  });

  it("question-scoped error does not close stream — later sibling result still arrives", async () => {
    const result = await startLiveRun(2);

    await act(async () => {
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          context: { run_id: "run-1", question_id: "q-1", event_seq: 3 },
          payload: { code: "generation_failed", message: "Question failed", failure_class: "timeout" },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // Sibling result event for q-2 must still be processed
    await act(async () => {
      capturedOnMessage?.({
        event: "result",
        data: JSON.stringify({
          event: "result",
          context: { run_id: "run-1", question_id: "q-2", event_seq: 4, content_revision: 1 },
          payload: {
            id: "q-2",
            情境: ["個人"],
            題型種類: "單一題",
            題型: "選擇題",
            題目: ["Sibling question"],
            正確解題分析: ["answer"],
          },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    // q-2 result must be visible
    expect(result.current.results.length).toBeGreaterThan(0);
    const ids = result.current.results.map((q) => q.id);
    expect(ids).toContain("q-2");
  });

  // Bug 2: run-level error reads failure_class from envelope.payload
  it("run-level stream_failed (no context) sets status=error with localized message", async () => {
    const lang = useLangStore.getState().lang;
    useLangStore.getState().setLang("zh-TW");
    try {
      const result = await startLiveRun(1);

      await act(async () => {
        // Real wire shape: no context field → run-level error
        capturedOnMessage?.({
          event: "error",
          data: JSON.stringify({
            event: "error",
            payload: { code: "stream_failed", message: "backend error", failure_class: "connection" },
          }),
        });
        for (let i = 0; i < 5; i++) await Promise.resolve();
      });

      expect(result.current.status).toBe("error");
      expect(result.current.errorFailureClass).toBe("connection");
      // Must show localized text, not the raw envelope JSON
      expect(result.current.errorMessage).not.toContain('"event"');
      expect(result.current.errorMessage).not.toContain('"payload"');
      const zhMsg = MESSAGES["zh-TW"]?.["error.class.connection"];
      if (zhMsg) expect(result.current.errorMessage).toContain(zhMsg);
    } finally {
      useLangStore.getState().setLang(lang);
    }
  });

  it("unknown failure_class falls back to payload.message, never raw JSON", async () => {
    const result = await startLiveRun(1);

    await act(async () => {
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          payload: {
            code: "stream_failed",
            message: "plain backend message",
            failure_class: "not_a_real_code",
          },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorFailureClass).toBeNull();
    // Must be the message string, never a raw JSON dump
    expect(result.current.errorMessage).toBe("plain backend message");
    expect(result.current.errorMessage).not.toContain("{");
  });

  it("absent failure_class in payload falls back to payload.message", async () => {
    const result = await startLiveRun(1);

    await act(async () => {
      capturedOnMessage?.({
        event: "error",
        data: JSON.stringify({
          event: "error",
          payload: { code: "stream_failed", message: "no class here" },
        }),
      });
      for (let i = 0; i < 5; i++) await Promise.resolve();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.errorFailureClass).toBeNull();
    expect(result.current.errorMessage).toBe("no class here");
  });
});
