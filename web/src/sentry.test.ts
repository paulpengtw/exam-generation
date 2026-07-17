import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.hoisted(() => vi.fn());
const feedbackIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Feedback" })),
);

vi.mock("@sentry/react", () => ({
  init: initMock,
  feedbackIntegration: feedbackIntegrationMock,
}));

// initSentry() now guards on a module-level `_initialized` flag, so each
// test resets the module registry and re-imports fresh to keep tests
// independent (otherwise the flag set by an earlier test would suppress
// init in a later one).
let initSentry: typeof import("./sentry").initSentry;
let isSentryEnabled: typeof import("./sentry").isSentryEnabled;

beforeEach(async () => {
  vi.resetModules();
  ({ initSentry, isSentryEnabled } = await import("./sentry"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("sentry module", () => {
  it("is disabled and skips init when VITE_SENTRY_DSN is empty", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    expect(isSentryEnabled()).toBe(false);
    initSentry();
    expect(initMock).not.toHaveBeenCalled();
  });

  it("initializes with DSN, production environment, and a non-injecting feedback integration", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    vi.stubEnv("VITE_IS_STAGING", "");
    expect(isSentryEnabled()).toBe(true);
    initSentry();
    expect(initMock).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: "https://key@o0.ingest.sentry.io/0",
        environment: "production",
      }),
    );
    expect(feedbackIntegrationMock).toHaveBeenCalledWith(
      expect.objectContaining({ autoInject: false, showBranding: false }),
    );
  });

  it("uses the staging environment when VITE_IS_STAGING is set", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    vi.stubEnv("VITE_IS_STAGING", "1");
    initSentry();
    expect(initMock).toHaveBeenCalledWith(
      expect.objectContaining({ environment: "staging" }),
    );
  });

  it("only initializes Sentry once across multiple calls (idempotent)", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    initSentry();
    initSentry();
    expect(initMock).toHaveBeenCalledTimes(1);
  });
});
