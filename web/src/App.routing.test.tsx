import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const authStoreMock = vi.hoisted(() => ({
  authenticated: false,
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("./pages/LoginPage", () => ({
  default: () => <div data-testid="page-login" />,
}));

vi.mock("./pages/VerifyPage", () => ({
  default: () => <div data-testid="page-verify" />,
}));

vi.mock("./pages/GeneratePage", () => ({
  default: ({ subject }: { subject?: string }) => (
    <div data-testid="page-generate" data-subject={subject} />
  ),
}));

vi.mock("./pages/HistoryPage", () => ({
  default: () => <div data-testid="page-history" />,
}));

vi.mock("./pages/SubjectSelectPage", () => ({
  default: () => <div data-testid="page-subject-select" />,
}));

vi.mock("./pages/FidelityComparePage", () => ({
  default: () => <div data-testid="page-fidelity-compare" />,
}));

vi.mock("./components/StagingBanner", () => ({
  default: () => <div data-testid="chrome-staging-banner" />,
}));

vi.mock("./components/FeedbackButton", () => ({
  default: () => <div data-testid="chrome-feedback-button" />,
}));

vi.mock("./store/authStore", () => ({
  useAuthStore: (
    selector: (state: {
      token: string | null;
      user: null;
      login: typeof authStoreMock.login;
      logout: typeof authStoreMock.logout;
      isAuthenticated: () => boolean;
    }) => unknown,
  ) =>
    selector({
      token: authStoreMock.authenticated ? "test-token" : null,
      user: null,
      login: authStoreMock.login,
      logout: authStoreMock.logout,
      isAuthenticated: () => authStoreMock.authenticated,
    }),
}));

import App from "./App";

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const routeCases = [
  { path: "/", testId: "page-login" },
  { path: "/verify", testId: "page-verify" },
  { path: "/generate", testId: "page-subject-select" },
  { path: "/generate/math", testId: "page-generate", subject: "math" },
  {
    path: "/generate/social_studies",
    testId: "page-generate",
    subject: "social_studies",
  },
  {
    path: "/generate/natural_sciences",
    testId: "page-generate",
    subject: "natural_sciences",
  },
  { path: "/history", testId: "page-history" },
  { path: "/history/route-table-id", testId: "page-history" },
  { path: "/fidelity-compare", testId: "page-fidelity-compare" },
] as const;

const protectedRouteCases = [
  { path: "/generate", protectedTestId: "page-subject-select" },
  { path: "/generate/math", protectedTestId: "page-generate" },
  { path: "/generate/social_studies", protectedTestId: "page-generate" },
  { path: "/generate/natural_sciences", protectedTestId: "page-generate" },
  { path: "/history", protectedTestId: "page-history" },
  { path: "/history/abc123", protectedTestId: "page-history" },
] as const;

const publicRouteCases = [
  { path: "/", testId: "page-login" },
  { path: "/verify", testId: "page-verify" },
  { path: "/fidelity-compare", testId: "page-fidelity-compare" },
] as const;

describe("App routing regression net", () => {
  beforeEach(() => {
    authStoreMock.authenticated = false;
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState({}, "", "/");
  });

  describe("authenticated routes", () => {
    it.each(routeCases)(
      "renders $testId at $path",
      ({ path, testId, subject }) => {
        authStoreMock.authenticated = true;

        renderAt(path);

        const page = screen.getByTestId(testId);
        expect(page).toBeInTheDocument();
        if (subject !== undefined) {
          expect(page).toHaveAttribute("data-subject", subject);
        }
      },
    );
  });

  describe("protected routes", () => {
    it.each(protectedRouteCases)(
      "redirects unauthenticated visitors from $path to login",
      async ({ path, protectedTestId }) => {
        renderAt(path);

        expect(await screen.findByTestId("page-login")).toBeInTheDocument();
        expect(screen.queryByTestId(protectedTestId)).not.toBeInTheDocument();
        expect(window.location.pathname).toBe("/");
      },
    );
  });

  describe("public routes", () => {
    it.each(publicRouteCases)(
      "renders $testId at $path while unauthenticated",
      ({ path, testId }) => {
        renderAt(path);

        expect(screen.getByTestId(testId)).toBeInTheDocument();
      },
    );
  });

  it.each(["/", "/verify", "/generate/math", "/history/abc123"])(
    "renders shared chrome at %s",
    (path) => {
      authStoreMock.authenticated = true;

      renderAt(path);

      expect(screen.getByTestId("chrome-staging-banner")).toBeInTheDocument();
      expect(screen.getByTestId("chrome-feedback-button")).toBeInTheDocument();
    },
  );

  it("resolves /history/abc123 to HistoryPage", () => {
    authStoreMock.authenticated = true;

    renderAt("/history/abc123");

    expect(screen.getByTestId("page-history")).toBeInTheDocument();
  });
});
