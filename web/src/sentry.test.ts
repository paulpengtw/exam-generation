import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.hoisted(() => vi.fn());
const setUserMock = vi.hoisted(() => vi.fn());
const feedbackIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Feedback" })),
);
const browserTracingIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "BrowserTracing" })),
);
const consoleLoggingIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "ConsoleLogs" })),
);
const replayIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Replay" })),
);

vi.mock("@sentry/react", () => ({
  init: initMock,
  setUser: setUserMock,
  feedbackIntegration: feedbackIntegrationMock,
  browserTracingIntegration: browserTracingIntegrationMock,
  consoleLoggingIntegration: consoleLoggingIntegrationMock,
  replayIntegration: replayIntegrationMock,
}));

// initSentry() now guards on a module-level `_initialized` flag, so each
// test resets the module registry and re-imports fresh to keep tests
// independent (otherwise the flag set by an earlier test would suppress
// init in a later one).
let initSentry: typeof import("./sentry").initSentry;
let isSentryEnabled: typeof import("./sentry").isSentryEnabled;
let scrubMagicLinkToken: typeof import("./sentry").scrubMagicLinkToken;

beforeEach(async () => {
  localStorage.clear();
  vi.resetModules();
  ({ initSentry, isSentryEnabled, scrubMagicLinkToken } = await import(
    "./sentry"
  ));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("sentry module", () => {
  it("scrubs only token and email query values from magic-link URLs", () => {
    expect(
      scrubMagicLinkToken(
        "/verify?token=abc123&email=x@y.z&next=/exams#complete",
      ),
    ).toBe(
      "/verify?token=[Filtered]&email=[Filtered]&next=/exams#complete",
    );
    expect(scrubMagicLinkToken("/exams?status=draft#recent")).toBe(
      "/exams?status=draft#recent",
    );
  });

  it("scrubs magic-link URLs from error events without dropping ordinary events", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const beforeSend = initMock.mock.calls[0][0].beforeSend;
    const event = {
      request: {
        url: "/verify?token=url-token&email=url@example.com&next=/exams",
        query_string:
          "token=query-token&email=query@example.com&next=/exams",
      },
    };

    expect(beforeSend(event, {})).toBe(event);
    expect(event).toEqual({
      request: {
        url: "/verify?token=[Filtered]&email=[Filtered]&next=/exams",
        query_string:
          "token=[Filtered]&email=[Filtered]&next=/exams",
      },
    });

    const ordinaryEvent = {
      request: { url: "/exams?status=draft", query_string: "status=draft" },
    };
    expect(beforeSend(ordinaryEvent, {})).toBe(ordinaryEvent);
    expect(ordinaryEvent).toEqual({
      request: { url: "/exams?status=draft", query_string: "status=draft" },
    });
  });

  it("scrubs magic-link URLs from transactions without dropping ordinary transactions", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const beforeSendTransaction =
      initMock.mock.calls[0][0].beforeSendTransaction;
    const transaction = {
      transaction:
        "GET /verify?token=transaction-token&email=trace@example.com&next=/exams",
      request: {
        url: "/verify?token=request-token&email=request@example.com",
        query_string: "token=query-token&email=query@example.com",
      },
    };

    expect(beforeSendTransaction(transaction, {})).toBe(transaction);
    expect(transaction).toEqual({
      transaction:
        "GET /verify?token=[Filtered]&email=[Filtered]&next=/exams",
      request: {
        url: "/verify?token=[Filtered]&email=[Filtered]",
        query_string: "token=[Filtered]&email=[Filtered]",
      },
    });

    const ordinaryTransaction = { transaction: "GET /exams?status=draft" };
    expect(beforeSendTransaction(ordinaryTransaction, {})).toBe(
      ordinaryTransaction,
    );
    expect(ordinaryTransaction).toEqual({
      transaction: "GET /exams?status=draft",
    });
  });

  it("scrubs magic-link URLs from breadcrumb strings without dropping ordinary breadcrumbs", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    initSentry();
    const beforeBreadcrumb = initMock.mock.calls[0][0].beforeBreadcrumb;
    const breadcrumb = {
      category: "navigation",
      message: "/verify?token=message-token&email=message@example.com",
      data: {
        from: "/verify?token=from-token&email=from@example.com",
        to: "/verify?token=to-token&email=to@example.com",
        url: "/verify?token=url-token&email=url@example.com",
        method: "GET",
        status_code: 200,
      },
    };

    expect(beforeBreadcrumb(breadcrumb)).toBe(breadcrumb);
    expect(breadcrumb).toEqual({
      category: "navigation",
      message: "/verify?token=[Filtered]&email=[Filtered]",
      data: {
        from: "/verify?token=[Filtered]&email=[Filtered]",
        to: "/verify?token=[Filtered]&email=[Filtered]",
        url: "/verify?token=[Filtered]&email=[Filtered]",
        method: "GET",
        status_code: 200,
      },
    });

    const ordinaryBreadcrumb = {
      message: "/exams?status=draft",
      data: { to: "/exams?status=draft", status_code: 200 },
    };
    expect(beforeBreadcrumb(ordinaryBreadcrumb)).toBe(ordinaryBreadcrumb);
    expect(ordinaryBreadcrumb).toEqual({
      message: "/exams?status=draft",
      data: { to: "/exams?status=draft", status_code: 200 },
    });
  });

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

  it("enables tracing only for same-origin relative requests", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");

    initSentry();

    const options = initMock.mock.calls[0][0];
    expect(browserTracingIntegrationMock).toHaveBeenCalledOnce();
    expect(options.tracesSampleRate).toBe(1);
    expect(options.tracePropagationTargets).toEqual([/^\//]);
    expect(options.tracePropagationTargets[0].test("/auth/verify")).toBe(true);
    expect(
      options.tracePropagationTargets.some((target: string | RegExp) =>
        String(target).includes("yourserver.io"),
      ),
    ).toBe(false);
  });

  it("records replays in buffer mode", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");

    initSentry();

    const options = initMock.mock.calls[0][0];
    expect(options.replaysSessionSampleRate).toBe(0);
    expect(options.replaysOnErrorSampleRate).toBe(1);
  });

  it("masks replay content except for explicitly allowlisted chrome", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");

    initSentry();

    expect(replayIntegrationMock).toHaveBeenCalledWith({
      maskAllText: true,
      blockAllMedia: true,
      unmask: [".sentry-unmask"],
    });
  });

  it("pins every allowed data-collection category", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");

    initSentry();

    expect(initMock.mock.calls[0][0].dataCollection).toEqual({
      userInfo: false,
      httpHeaders: {
        request: { allow: [] },
        response: { allow: [] },
      },
      httpBodies: [],
      genAI: { inputs: false, outputs: false },
      cookies: false,
      queryParams: { allow: [] },
    });
  });

  it("forwards only warn and error console calls as logs", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");

    initSentry();

    expect(initMock.mock.calls[0][0].enableLogs).toBe(true);
    expect(consoleLoggingIntegrationMock).toHaveBeenCalledWith({
      levels: ["warn", "error"],
    });
  });

  it("includes the build release when VITE_SENTRY_RELEASE is set", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://key@o0.ingest.sentry.io/0");
    vi.stubEnv("VITE_SENTRY_RELEASE", "9cffb64");

    initSentry();

    expect(initMock.mock.calls[0][0]).toHaveProperty("release", "9cffb64");
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
