import * as Sentry from "@sentry/react";

/** True when a Sentry DSN was provided at build time. */
export function isSentryEnabled(): boolean {
  return Boolean(import.meta.env.VITE_SENTRY_DSN);
}

/**
 * Initialize Sentry error monitoring + the user-feedback integration.
 * No-op when VITE_SENTRY_DSN is unset — the app must never contact
 * Sentry in that case. The feedback widget's default floating button
 * is disabled; FeedbackButton opens the form explicitly.
 */
export function initSentry(): void {
  if (!isSentryEnabled()) return;
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_IS_STAGING ? "staging" : "production",
    integrations: [
      Sentry.feedbackIntegration({ autoInject: false, showBranding: false }),
    ],
  });
}
