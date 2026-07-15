# Design: Bottom-right "?" error-report button (GitHub issue #125)

**Date:** 2026-07-15
**Issue:** [#125](https://github.com/paulpengtw/exam-generation/issues/125) — add question mark error report btn at bottom-right and invoke opensource existing report error pipeline that could direct file a new issue to github repo

## Decision summary

| Decision | Choice |
|---|---|
| Pipeline | Third-party feedback widget (not prefilled GitHub URL, not in-house form) |
| Tool | Sentry browser SDK + User Feedback integration |
| Hosting | sentry.io SaaS (free developer tier) |
| Button UI | Custom "?" floating button that opens the Sentry feedback dialog (no auto-injected Sentry button) |
| Scope | Feedback widget **plus** automatic error monitoring (uncaught exceptions, breadcrumbs) |
| GitHub flow | Manual one-click "Create GitHub Issue" from the Sentry UI via Sentry's GitHub integration (auto-filing via alert rules is a paid Sentry feature; not used) |

## Overview

A floating "?" button appears at the bottom-right of every page of the web app
(`web/`). Clicking it opens Sentry's User Feedback dialog (name / email /
message, optional screenshot). Reports land in the Sentry project, where the
installed GitHub integration provides one-click creation of a pre-filled,
linked issue in `paulpengtw/exam-generation`. Because the SDK is initialized
with error capture enabled, feedback arrives with breadcrumbs/context and
crashes are reported even when users file nothing.

The repo is private, so a prefilled `github.com/.../issues/new` URL would only
work for team members; Sentry decouples reporters from repo access.

## Frontend changes (all in `web/`)

1. **Dependency:** add `@sentry/react`.

2. **`web/src/sentry.ts`** (new): initializes Sentry once at app startup.
   - `dsn: import.meta.env.VITE_SENTRY_DSN`
   - `environment`: `"staging"` when `VITE_IS_STAGING` is truthy, else
     `"production"` (same env-var pattern as `StagingBanner.tsx`).
   - `Sentry.feedbackIntegration({ autoInject: false, showBranding: false })`
     — no default Sentry button is injected.
   - **No-DSN behavior:** if `VITE_SENTRY_DSN` is empty/undefined, `Sentry.init`
     is skipped entirely. Exports a helper (e.g. `isSentryEnabled()`) so the
     button can hide itself. The app must work identically without a DSN
     (local dev default) — zero network calls to Sentry.
   - Imported from `web/src/main.tsx` before rendering.

3. **`web/src/components/FeedbackButton.tsx`** (new): a small fixed circular
   button (`fixed bottom-4 right-4`, Tailwind, styled consistently with the
   app) labeled "?" with an accessible `aria-label`.
   - On click, fetches the feedback integration
     (`Sentry.getFeedback()`), calls `createForm()` with dialog label options
     pulled from the i18n table via `useT()`, then `appendToDom()`/`open()`.
     Building the form per-click (instead of configuring labels at init time)
     is what lets the dialog follow the current zh-TW / en-US language.
   - Renders `null` when Sentry is not enabled.

4. **`web/src/App.tsx`**: mount `<FeedbackButton />` as a sibling of
   `<StagingBanner />` inside `BrowserRouter`, so it appears on every route,
   including login/verify.

5. **i18n (`web/src/i18n/messages.ts`)**: new keys under a `feedback.`
   prefix for both `en-US` and `zh-TW`: dialog title, message
   label/placeholder, name/email labels, submit button, cancel button,
   success message, and the button `aria-label`.

6. **Build wiring:**
   - `web/Dockerfile`: add `ARG VITE_SENTRY_DSN` / `ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN`
     (same pattern as `VITE_IS_STAGING`).
   - `docker-compose.yml`: pass the build arg through.
   - Document in `web/README.md` and `DEPLOYMENT.md`. The DSN is a public
     client key, not a secret.

## Sentry-side setup (manual, documented — no code)

Checklist added to `DEPLOYMENT.md`:

1. Create a sentry.io organization/project (platform: React); copy the DSN.
2. Set `VITE_SENTRY_DSN` at build time for staging/production.
3. Install the **GitHub integration** in the Sentry org settings and connect
   the `paulpengtw/exam-generation` repository.
4. Triage flow: open a feedback/error item in Sentry → "Create GitHub Issue"
   → a pre-filled, linked issue is filed in the repo.

## Error handling & privacy

- No DSN → button hidden, SDK not initialized, no network calls.
- Feedback submission failures are surfaced by the Sentry dialog's built-in
  error state; no custom handling needed.
- Frontend-only change; no FastAPI/backend modifications, no stored GitHub
  token.

## Testing

- **Vitest** (`web/src/components/FeedbackButton.test.tsx`, mirroring the
  style of `QuestionCard.test.tsx`, with `@sentry/react` mocked):
  - renders the "?" button when Sentry is enabled;
  - renders nothing when Sentry is disabled (no DSN);
  - clicking the button invokes the feedback form creation/open path.
- **Manual verification:** build with a real DSN, submit a feedback report,
  confirm it appears in Sentry's User Feedback view, and confirm the
  "Create GitHub Issue" button files a linked issue in the private repo.

## Out of scope

- Automatic GitHub issue creation for every report (paid alert-rule feature /
  webhook handler) — revisit only if manual triage becomes a bottleneck.
- Backend (FastAPI) instrumentation with Sentry.
- Session replay, performance tracing, or other Sentry products.
