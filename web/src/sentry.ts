import * as Sentry from "@sentry/react";
import { useAuthStore } from "./store/authStore";

let _initialized = false;

/** True when a Sentry DSN was provided at build time. */
export function isSentryEnabled(): boolean {
  return Boolean(import.meta.env.VITE_SENTRY_DSN);
}

/** Remove credentials embedded in magic-link query parameters. */
export function scrubMagicLinkToken(url: string): string {
  return url.replace(/(^|[?&])((?:token|email)=)[^&#]*/g, "$1$2[Filtered]");
}

/**
 * Initialize Sentry error monitoring + the user-feedback integration.
 * Idempotent — safe to call more than once; Sentry is only initialized
 * on the first call. No-op when VITE_SENTRY_DSN is unset — the app must
 * never contact Sentry in that case. The feedback widget's default
 * floating button is disabled; FeedbackButton opens the form explicitly.
 */
export function initSentry(): void {
  if (!isSentryEnabled() || _initialized) return;
  _initialized = true;
  const release = import.meta.env.VITE_SENTRY_RELEASE;
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_IS_STAGING ? "staging" : "production",
    ...(release ? { release } : {}),
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
        unmask: [".sentry-unmask"],
      }),
      Sentry.consoleLoggingIntegration({ levels: ["warn", "error"] }),
      Sentry.feedbackIntegration({ autoInject: false, showBranding: false }),
    ],
    tracesSampleRate: 1,
    tracePropagationTargets: [/^\//],
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
    enableLogs: true,
    // Metrics default to enabled in @sentry/react 10.66, so no flag is needed.
    dataCollection: {
      userInfo: false,
      httpHeaders: {
        request: { allow: [] },
        response: { allow: [] },
      },
      httpBodies: [],
      genAI: { inputs: false, outputs: false },
      cookies: false,
      queryParams: { allow: [] },
    },
    beforeSend(event) {
      if (event.request?.url) {
        event.request.url = scrubMagicLinkToken(event.request.url);
      }
      if (typeof event.request?.query_string === "string") {
        event.request.query_string = scrubMagicLinkToken(
          event.request.query_string,
        );
      }
      return event;
    },
    beforeSendTransaction(event) {
      if (event.request?.url) {
        event.request.url = scrubMagicLinkToken(event.request.url);
      }
      if (typeof event.request?.query_string === "string") {
        event.request.query_string = scrubMagicLinkToken(
          event.request.query_string,
        );
      }
      if (event.transaction) {
        event.transaction = scrubMagicLinkToken(event.transaction);
      }
      return event;
    },
    beforeBreadcrumb(breadcrumb) {
      if (typeof breadcrumb.message === "string") {
        breadcrumb.message = scrubMagicLinkToken(breadcrumb.message);
      }
      for (const key of ["from", "to", "url"]) {
        const value = breadcrumb.data?.[key];
        if (typeof value === "string") {
          breadcrumb.data![key] = scrubMagicLinkToken(value);
        }
      }
      return breadcrumb;
    },
  });

  const user = useAuthStore.getState().user;
  if (user) {
    Sentry.setUser({ id: user.email, email: user.email });
  }
  useAuthStore.subscribe((state, previousState) => {
    if (state.user) {
      Sentry.setUser({ id: state.user.email, email: state.user.email });
    } else if (previousState.user) {
      Sentry.setUser(null);
    }
  });
}
