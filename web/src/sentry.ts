import * as Sentry from "@sentry/react";

let _initialized = false;

/** True when a Sentry DSN was provided at build time. */
export function isSentryEnabled(): boolean {
  return Boolean(import.meta.env.VITE_SENTRY_DSN);
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
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_IS_STAGING ? "staging" : "production",
    integrations: [
      Sentry.feedbackIntegration({ autoInject: false, showBranding: false }),
    ],
  });
}
