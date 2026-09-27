/**
 * Test (e): Masking — question content, conflict payloads, and preview markup
 * must never reach telemetry (Sentry breadcrumbs, console, analytics).
 *
 * Extends existing sentry.test.ts with branch-specific masking assertions:
 * 1. genAI data collection is disabled (inputs AND outputs = false)
 * 2. All text is masked by default in replays; only .sentry-unmask chrome passes
 * 3. Console capture is restricted to warn/error (no info/debug that could log
 *    question content)
 * 4. HTTP body collection is empty (no request/response body capture)
 * 5. Query parameter collection is empty (prevents URL-embedded content leaking)
 *
 * These settings collectively prevent question content, conflict payload data,
 * and ODT preview markup from reaching Sentry.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.hoisted(() => vi.fn());
const replayIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Replay" })),
);
const consoleLoggingIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "ConsoleLogs" })),
);
const feedbackIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Feedback" })),
);
const browserTracingIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "BrowserTracing" })),
);

vi.mock("@sentry/react", () => ({
  init: initMock,
  setUser: vi.fn(),
  feedbackIntegration: feedbackIntegrationMock,
  browserTracingIntegration: browserTracingIntegrationMock,
  consoleLoggingIntegration: consoleLoggingIntegrationMock,
  replayIntegration: replayIntegrationMock,
}));

let initSentry: typeof import("./sentry").initSentry;

beforeEach(async () => {
  localStorage.clear();
  vi.resetModules();
  ({ initSentry } = await import("./sentry"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("754 masking — question content, conflict payloads, preview markup", () => {
  it("genAI inputs and outputs are both disabled — question content never captured", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const options = initMock.mock.calls[0][0];
    expect(options.dataCollection?.genAI).toEqual({ inputs: false, outputs: false });
  });

  it("HTTP bodies collection is empty — no request/response body capture of question content", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const options = initMock.mock.calls[0][0];
    expect(options.dataCollection?.httpBodies).toEqual([]);
  });

  it("query parameter collection is empty — URL-embedded content params are excluded", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const options = initMock.mock.calls[0][0];
    expect(options.dataCollection?.queryParams).toEqual({ allow: [] });
  });

  it("replay is maskAllText=true — conflict reason codes and preview markup are masked", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    expect(replayIntegrationMock).toHaveBeenCalledWith(
      expect.objectContaining({ maskAllText: true, blockAllMedia: true }),
    );
  });

  it("replay only unmasks .sentry-unmask elements — structural chrome, not question content", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const replayArgs = replayIntegrationMock.mock.calls[0][0] as { unmask: string[] };
    expect(replayArgs.unmask).toEqual([".sentry-unmask"]);
    // Verify conflict-reason spans, ODT preview markup, and question body
    // are NOT in the unmask list (they must not have .sentry-unmask class)
    expect(replayArgs.unmask).not.toContain(".conflict-reason");
    expect(replayArgs.unmask).not.toContain(".odt-preview");
    expect(replayArgs.unmask).not.toContain(".question-body");
  });

  it("console logging is limited to warn/error — no info/debug paths for question text", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    expect(consoleLoggingIntegrationMock).toHaveBeenCalledWith({ levels: ["warn", "error"] });
    // Confirm info/debug/log are excluded so question content logged at those levels
    // never reaches Sentry
    const levels = consoleLoggingIntegrationMock.mock.calls[0][0].levels as string[];
    expect(levels).not.toContain("info");
    expect(levels).not.toContain("debug");
    expect(levels).not.toContain("log");
  });

  it("HTTP request and response headers are not collected", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const options = initMock.mock.calls[0][0];
    expect(options.dataCollection?.httpHeaders).toEqual({
      request: { allow: [] },
      response: { allow: [] },
    });
  });

  it("user info collection is disabled", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const options = initMock.mock.calls[0][0];
    expect(options.dataCollection?.userInfo).toBe(false);
  });

  it("breadcrumb hook does not forward question content (ordinary breadcrumbs pass unchanged)", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const beforeBreadcrumb = initMock.mock.calls[0][0].beforeBreadcrumb as (
      b: Record<string, unknown>,
    ) => Record<string, unknown>;

    // A navigation breadcrumb passes through unchanged
    const navBreadcrumb = {
      category: "navigation",
      data: { from: "/generate", to: "/history" },
    };
    const result = beforeBreadcrumb(navBreadcrumb);
    expect(result).toBe(navBreadcrumb);

    // The hook does not inject question content into breadcrumbs
    const plain = { category: "ui.click", message: "button.download-json" };
    expect(beforeBreadcrumb(plain)).toBe(plain);
  });
});
