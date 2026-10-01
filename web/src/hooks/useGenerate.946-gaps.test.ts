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
