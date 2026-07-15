# Error-Report "?" Button (Sentry User Feedback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a floating "?" button at the bottom-right of every web-app page that opens Sentry's User Feedback dialog; reports land in sentry.io where the GitHub integration files linked issues in `paulpengtw/exam-generation` (GitHub issue #125).

**Architecture:** Frontend-only change in `web/` (React 19 + Vite + Tailwind 4). A new `sentry.ts` module initializes `@sentry/react` (error monitoring + feedback integration, no auto-injected button) only when `VITE_SENTRY_DSN` is set at build time. A new `FeedbackButton` component renders the "?" button globally and opens the Sentry feedback form per-click with labels from the existing i18n table. Sentry-side setup (project creation, GitHub integration) is documented in `DEPLOYMENT.md`, not coded.

**Tech Stack:** `@sentry/react` (v10, latest), Vite env vars (`VITE_SENTRY_DSN`), Tailwind CSS, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-15-error-report-button-design.md`

## Global Constraints

- No backend (`server/`) changes at all.
- With no `VITE_SENTRY_DSN`, the app behaves exactly as today: no Sentry init, no network calls, no visible button.
- The button appears on **every** route (login, verify, subject select, all three generate pages).
- All new i18n keys use the `feedback.` prefix and exist in **both** `en-US` and `zh-TW`.
- `VITE_SENTRY_DSN` is a build-time Vite variable (public client key, not a secret), wired the same way as the existing `VITE_IS_STAGING`.
- Sentry's default floating button must never appear (`autoInject: false`); only our custom "?" button.
- All web commands run from `/workspace/exam-generation/web/`.

## Pre-existing defect this plan fixes first

Commit `d534147` ("fix: remove unused fireEvent import that broke tsc build") also silently removed vitest and all testing-library devDependencies plus the `test`/`test:watch` scripts from `web/package.json` — while `web/vitest.config.ts`, `web/src/test/setup.ts`, and two `*.test.tsx` files remain in the tree. Task 1 restores the test tooling so this plan's TDD cycle (and the existing tests) can run. Test files are excluded from `tsc -b` via `tsconfig.app.json` `exclude`, so restoring them does not affect the production build.

---

### Task 1: Restore web test tooling

**Files:**
- Modify: `web/package.json` (scripts + devDependencies)
- Modify: `web/package-lock.json` (via npm)

**Interfaces:**
- Consumes: nothing.
- Produces: working `npm test` (vitest run) command used by every later task.

- [ ] **Step 1: Reinstall the test devDependencies**

```bash
cd /workspace/exam-generation/web
npm install -D vitest @vitest/ui jsdom @testing-library/jest-dom @testing-library/react @testing-library/user-event
```

- [ ] **Step 2: Restore the test scripts in `web/package.json`**

In the `"scripts"` block, after `"preview": "vite preview"`, add (matching what commit `4b09f45` originally had):

```json
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 3: Run the existing test suite to verify it passes**

Run: `npm test`
Expected: PASS — 2 test files (`src/components/QuestionCard.test.tsx`, `src/components/CoreQuestionPicker.test.tsx`), all tests green.

- [ ] **Step 4: Verify the production build still works (test deps must not leak into it)**

Run: `npm run build`
Expected: `tsc -b && vite build` succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json
git commit -m "fix(web): restore vitest + testing-library tooling removed by d534147"
```

---

### Task 2: Sentry initialization module

**Files:**
- Create: `web/src/sentry.ts`
- Create: `web/src/sentry.test.ts`
- Modify: `web/src/main.tsx`
- Modify: `web/package.json` (add `@sentry/react` dependency)

**Interfaces:**
- Consumes: `import.meta.env.VITE_SENTRY_DSN`, `import.meta.env.VITE_IS_STAGING` (Vite build-time env).
- Produces:
  - `isSentryEnabled(): boolean` — true iff `VITE_SENTRY_DSN` is a non-empty string. Task 3's `FeedbackButton` imports this from `../sentry`.
  - `initSentry(): void` — idempotent app-startup init; no-op without DSN. Called once from `main.tsx`.

- [ ] **Step 1: Install the Sentry SDK**

```bash
cd /workspace/exam-generation/web
npm install @sentry/react
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/sentry.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

const initMock = vi.hoisted(() => vi.fn());
const feedbackIntegrationMock = vi.hoisted(() =>
  vi.fn(() => ({ name: "Feedback" })),
);

vi.mock("@sentry/react", () => ({
  init: initMock,
  feedbackIntegration: feedbackIntegrationMock,
}));

import { initSentry, isSentryEnabled } from "./sentry";

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
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test -- src/sentry.test.ts`
Expected: FAIL — cannot resolve `./sentry` (module does not exist yet).

- [ ] **Step 4: Write the implementation**

Create `web/src/sentry.ts`:

```ts
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- src/sentry.test.ts`
Expected: PASS — 3 tests green.

- [ ] **Step 6: Wire init into app startup**

Modify `web/src/main.tsx` — add the import and call it before `createRoot`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary.tsx'
import { useLangStore } from './store/langStore.ts'
import { initSentry } from './sentry.ts'

initSentry();

// Keep <html lang> in sync with persisted language choice
useLangStore.subscribe((state) => {
  document.documentElement.lang = state.lang;
});
document.documentElement.lang = useLangStore.getState().lang;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
```

- [ ] **Step 7: Verify full suite, lint, and build**

Run: `npm test && npm run lint && npm run build`
Expected: all tests pass, no lint errors, build succeeds.

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json src/sentry.ts src/sentry.test.ts src/main.tsx
git commit -m "feat(web): add opt-in Sentry init with feedback integration (#125)"
```

---

### Task 3: i18n keys + FeedbackButton component, mounted globally

**Files:**
- Modify: `web/src/i18n/messages.ts` (new `feedback.*` keys in both language blocks)
- Create: `web/src/components/FeedbackButton.tsx`
- Create: `web/src/components/FeedbackButton.test.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `isSentryEnabled()` from `web/src/sentry.ts` (Task 2); `Sentry.getFeedback()` from `@sentry/react`; `useT()` from `web/src/i18n/useT.ts`.
- Produces: `<FeedbackButton />` default export, rendered once in `App.tsx`.

- [ ] **Step 1: Add i18n keys**

In `web/src/i18n/messages.ts`, add to the `"en-US"` block, directly after the `"staging.banner"` line (~line 29):

```ts
    "feedback.button_aria": "Report a problem",
    "feedback.form_title": "Report a problem",
    "feedback.name_label": "Name",
    "feedback.email_label": "Email",
    "feedback.message_label": "Description",
    "feedback.message_placeholder": "What went wrong? What did you expect to happen?",
    "feedback.submit_label": "Send report",
    "feedback.cancel_label": "Cancel",
    "feedback.success_message": "Thank you for your report!",
```

And to the `"zh-TW"` block, directly after its `"staging.banner"` line (~line 192):

```ts
    "feedback.button_aria": "回報問題",
    "feedback.form_title": "回報問題",
    "feedback.name_label": "姓名",
    "feedback.email_label": "電子郵件",
    "feedback.message_label": "問題描述",
    "feedback.message_placeholder": "發生了什麼問題？您預期的結果是什麼？",
    "feedback.submit_label": "送出回報",
    "feedback.cancel_label": "取消",
    "feedback.success_message": "感謝您的回報！",
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/components/FeedbackButton.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const sentryState = vi.hoisted(() => ({ enabled: true }));
const formMock = vi.hoisted(() => ({
  appendToDom: vi.fn(),
  open: vi.fn(),
  removeFromDom: vi.fn(),
}));
const createFormMock = vi.hoisted(() =>
  vi.fn(() => Promise.resolve(formMock)),
);

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: () => sentryState.enabled,
}));

vi.mock("@sentry/react", () => ({
  getFeedback: () => ({ createForm: createFormMock }),
}));

import FeedbackButton from "./FeedbackButton";

describe("FeedbackButton", () => {
  beforeEach(() => {
    sentryState.enabled = true;
    vi.clearAllMocks();
  });

  it("renders nothing when Sentry is not configured", () => {
    sentryState.enabled = false;
    const { container } = render(<FeedbackButton />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a ? button and opens the localized feedback form on click", async () => {
    render(<FeedbackButton />);
    const btn = screen.getByRole("button", { name: "Report a problem" });
    expect(btn).toHaveTextContent("?");

    fireEvent.click(btn);

    await waitFor(() => expect(formMock.open).toHaveBeenCalled());
    expect(createFormMock).toHaveBeenCalledWith(
      expect.objectContaining({
        formTitle: "Report a problem",
        submitButtonLabel: "Send report",
      }),
    );
    expect(formMock.appendToDom).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test -- src/components/FeedbackButton.test.tsx`
Expected: FAIL — cannot resolve `./FeedbackButton`.

- [ ] **Step 4: Write the component**

Create `web/src/components/FeedbackButton.tsx`:

```tsx
import * as Sentry from "@sentry/react";
import { useT } from "../i18n/useT";
import { isSentryEnabled } from "../sentry";

/**
 * Floating bottom-right "?" button that opens Sentry's user-feedback
 * dialog. The form is created per-click so its labels follow the
 * currently selected language. Hidden entirely when no DSN is set.
 */
export default function FeedbackButton() {
  const t = useT();
  if (!isSentryEnabled()) return null;

  const openFeedback = async () => {
    const feedback = Sentry.getFeedback();
    if (!feedback) return;
    const form = await feedback.createForm({
      formTitle: t("feedback.form_title"),
      nameLabel: t("feedback.name_label"),
      emailLabel: t("feedback.email_label"),
      messageLabel: t("feedback.message_label"),
      messagePlaceholder: t("feedback.message_placeholder"),
      submitButtonLabel: t("feedback.submit_label"),
      cancelButtonLabel: t("feedback.cancel_label"),
      successMessageText: t("feedback.success_message"),
      onFormClose: () => form.removeFromDom(),
      onFormSubmitted: () => form.removeFromDom(),
    });
    form.appendToDom();
    form.open();
  };

  return (
    <button
      type="button"
      aria-label={t("feedback.button_aria")}
      title={t("feedback.button_aria")}
      onClick={openFeedback}
      className="fixed bottom-4 right-4 z-50 flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-lg font-bold text-white shadow-lg transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400"
    >
      ?
    </button>
  );
}
```

Note: if `tsc` rejects any of the `createForm` option names against the installed `@sentry/react` version's `FeedbackDialog` types, check the actual option names in `node_modules/@sentry/core/build/types/types-hoist/feedback/config.ts` and adjust — the names above (`formTitle`, `nameLabel`, `emailLabel`, `messageLabel`, `messagePlaceholder`, `submitButtonLabel`, `cancelButtonLabel`, `successMessageText`, `onFormClose`, `onFormSubmitted`) are the documented v8+ names. Keep the test's expectations in sync with any rename.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- src/components/FeedbackButton.test.tsx`
Expected: PASS — 2 tests green.

- [ ] **Step 6: Mount globally in App.tsx**

Modify `web/src/App.tsx` — import the component and render it as a sibling of `StagingBanner`, inside `BrowserRouter`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import AuthGuard from "./components/AuthGuard";
import StagingBanner from "./components/StagingBanner";
import FeedbackButton from "./components/FeedbackButton";
import LoginPage from "./pages/LoginPage";
import VerifyPage from "./pages/VerifyPage";
import GeneratePage from "./pages/GeneratePage";
import SubjectSelectPage from "./pages/SubjectSelectPage";

export default function App() {
  return (
    <BrowserRouter>
      <StagingBanner />
      <FeedbackButton />
      <Routes>
```

(The rest of the file — all `<Route>` elements and closing tags — is unchanged.)

- [ ] **Step 7: Verify full suite, lint, and build**

Run: `npm test && npm run lint && npm run build`
Expected: all tests pass, no lint errors, build succeeds.

- [ ] **Step 8: Commit**

```bash
git add src/i18n/messages.ts src/components/FeedbackButton.tsx src/components/FeedbackButton.test.tsx src/App.tsx
git commit -m "feat(web): add bottom-right ? feedback button opening Sentry dialog (#125)"
```

---

### Task 4: Build wiring + deployment docs

**Files:**
- Modify: `web/Dockerfile`
- Modify: `docker-compose.yml` (frontend service)
- Modify: `DEPLOYMENT.md` (new Sentry section)
- Modify: `web/README.md` (env var note)

**Interfaces:**
- Consumes: `VITE_SENTRY_DSN` read by `web/src/sentry.ts` (Task 2).
- Produces: the build arg plumbing that makes the DSN reach `import.meta.env` in Docker builds; operator documentation.

- [ ] **Step 1: Add the build arg to `web/Dockerfile`**

After the existing `VITE_IS_STAGING` lines (lines 6–7), add:

```dockerfile
ARG VITE_SENTRY_DSN
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
```

- [ ] **Step 2: Pass the build arg through `docker-compose.yml`**

Change the `frontend` service's `build` block to:

```yaml
  frontend:
    build:
      context: .
      dockerfile: web/Dockerfile
      args:
        VITE_SENTRY_DSN: ${VITE_SENTRY_DSN:-}
```

(`:-` default keeps builds working when the variable is unset — Sentry stays disabled.)

- [ ] **Step 3: Document setup in `DEPLOYMENT.md`**

Add a new section (near the other environment-variable documentation, after the section that mentions `VITE_API_BASE_URL` around line 263):

```markdown
## Error reporting (Sentry, optional)

The web app has a bottom-right "?" button that lets users report problems.
It is powered by [Sentry](https://sentry.io) User Feedback and is **entirely
optional** — when `VITE_SENTRY_DSN` is not set, the button is hidden and the
app never contacts Sentry.

One-time setup:

1. Create a free account at sentry.io and create a project (platform:
   **React**). Copy the project's **DSN** (a public client key, not a
   secret).
2. Set `VITE_SENTRY_DSN` to that DSN when building the frontend
   (docker-compose reads it from the environment / `.env` file). Staging
   builds are tagged with environment `staging` (via `VITE_IS_STAGING`),
   production builds with `production`.
3. In Sentry: **Settings → Integrations → GitHub**, install the GitHub
   integration and connect the `paulpengtw/exam-generation` repository.

Triage flow: user feedback and captured errors appear in the Sentry project
(User Feedback / Issues views). Open an item and use **Create GitHub Issue**
to file a pre-filled, linked issue in the repository — issue creation is a
deliberate one-click action, not automatic, to keep the tracker free of
duplicates.
```

- [ ] **Step 4: Note the env var in `web/README.md`**

Add at the end of `web/README.md`:

```markdown
## Environment variables

| Variable | Purpose |
|---|---|
| `VITE_IS_STAGING` | Non-empty value shows the staging banner and tags Sentry events with environment `staging`. |
| `VITE_SENTRY_DSN` | Sentry DSN (public client key). Enables error monitoring and the bottom-right "?" feedback button. Leave unset to disable Sentry entirely. |

Both are **build-time** Vite variables: set them before `npm run build` (or
as Docker build args — see `web/Dockerfile` and `docker-compose.yml`).
```

- [ ] **Step 5: Verify the build still works and compose config is valid**

Run: `npm run build && docker compose -f /workspace/exam-generation/docker-compose.yml config --quiet`
Expected: Vite build succeeds; `docker compose config` exits 0 (warning about unset `VITE_SENTRY_DSN` is acceptable).

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add web/Dockerfile docker-compose.yml DEPLOYMENT.md web/README.md
git commit -m "chore: wire VITE_SENTRY_DSN build arg and document Sentry setup (#125)"
```

---

### Task 5: Manual end-to-end verification (requires a real DSN)

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything above, plus a real sentry.io project DSN supplied by the operator.

- [ ] **Step 1: Run the dev server with a DSN**

```bash
cd /workspace/exam-generation/web
VITE_SENTRY_DSN="<real DSN from sentry.io>" npm run dev
```

- [ ] **Step 2: Verify the button and dialog**

In the browser: the "?" button appears bottom-right on the login page and on `/generate`. Clicking opens the feedback dialog with the current language's labels; switching languages (existing language switcher) and reopening shows the other language.

- [ ] **Step 3: Submit a report and check Sentry**

Submit a test message. In sentry.io, the report appears under **User Feedback**. With the GitHub integration installed, open it and click **Create GitHub Issue** — confirm a linked issue appears in `paulpengtw/exam-generation`.

- [ ] **Step 4: Verify the disabled path**

Run `npm run dev` **without** `VITE_SENTRY_DSN`: no button renders, and the browser network tab shows no requests to `sentry.io` / `ingest.sentry.io`.
