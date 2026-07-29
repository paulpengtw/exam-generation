import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.hoisted(() => vi.fn());
const setUserMock = vi.hoisted(() => vi.fn());
const feedbackIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Feedback" })),
);

vi.mock("@sentry/react", () => ({
  init: initMock,
  setUser: setUserMock,
  feedbackIntegration: feedbackIntegrationMock,
}));

// initSentry() now guards on a module-level `_initialized` flag, so each
// test resets the module registry and re-imports fresh to keep tests
// independent (otherwise the flag set by an earlier test would suppress
// init in a later one).
let initSentry: typeof import("./sentry").initSentry;
let isSentryEnabled: typeof import("./sentry").isSentryEnabled;

beforeEach(async () => {
  localStorage.clear();
  vi.resetModules();
  ({ initSentry, isSentryEnabled } = await import("./sentry"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("sentry module", () => {
  it("sets the persisted auth user after a page reload", async () => {
    const user = {
      id: "account-123",
      email: "teacher@example.com",
      created_at: "2026-07-29T00:00:00Z",
    };
    localStorage.setItem("auth_token", "persisted-token");
    localStorage.setItem("auth_user", JSON.stringify(user));
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    vi.resetModules();
    ({ initSentry, isSentryEnabled } = await import("./sentry"));

    initSentry();

    expect(setUserMock).toHaveBeenCalledWith({
      id: "teacher@example.com",
      email: "teacher@example.com",
    });
  });

  it("sets the Sentry user when a user logs in after initialization", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    const { useAuthStore } = await import("./store/authStore");
    initSentry();

    useAuthStore.getState().login("new-token", {
      id: "account-456",
      email: "new-teacher@example.com",
      created_at: "2026-07-29T00:00:00Z",
    });

    expect(setUserMock).toHaveBeenCalledWith({
      id: "new-teacher@example.com",
      email: "new-teacher@example.com",
    });
  });

  it("clears the Sentry user when the signed-in user logs out", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    const { useAuthStore } = await import("./store/authStore");
    initSentry();
    useAuthStore.getState().login("signed-in-token", {
      id: "account-789",
      email: "signed-in-teacher@example.com",
      created_at: "2026-07-29T00:00:00Z",
    });
    setUserMock.mockClear();

    useAuthStore.getState().logout();

    expect(setUserMock).toHaveBeenCalledWith(null);
  });

  it("is disabled and skips all Sentry user wiring when VITE_SENTRY_DSN is empty", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    localStorage.setItem("auth_token", "persisted-token");
    localStorage.setItem(
      "auth_user",
      JSON.stringify({
        id: "account-disabled",
        email: "disabled@example.com",
        created_at: "2026-07-29T00:00:00Z",
      }),
    );
    vi.resetModules();
    ({ initSentry, isSentryEnabled } = await import("./sentry"));
    const { useAuthStore } = await import("./store/authStore");

    expect(isSentryEnabled()).toBe(false);
    initSentry();
    useAuthStore.getState().logout();
    useAuthStore.getState().login("new-token", {
      id: "account-still-disabled",
      email: "still-disabled@example.com",
      created_at: "2026-07-29T00:00:00Z",
    });

    expect(initMock).not.toHaveBeenCalled();
    expect(setUserMock).not.toHaveBeenCalled();
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
