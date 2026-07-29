import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  createMemoryRouter,
  RouterProvider,
} from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { GeneratedQuestion } from "../hooks/useGenerate";

const generateMock = vi.hoisted(() => vi.fn());
const resetMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

let configuredDisplayResults: GeneratedQuestion[] = [];

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: [],
    displayResults: configuredDisplayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    generate: generateMock,
    reset: resetMock,
  }),
}));

vi.mock("../components/ParamForm", () => ({
  default: ({
    onUnsubmittedInput,
  }: {
    onUnsubmittedInput?: () => void;
  }) => (
    <button
      type="button"
      data-testid="edit-form"
      onClick={onUnsubmittedInput}
    >
      edit form
    </button>
  ),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: {
    user: null;
    logout: () => void;
  }) => unknown) => selector({ user: null, logout: logoutMock }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import GeneratePage from "./GeneratePage";

const GENERATED_QUESTION: GeneratedQuestion = {
  index: 0,
  question: {
    id: "question-1",
    情境: [],
    題型種類: "single",
    題型: "multiple_choice",
    題目: ["Question"],
    正確解題分析: ["Explanation"],
  },
  phase: "verified",
  isFinal: true,
};

function renderPage({ withResults = false } = {}) {
  configuredDisplayResults = withResults ? [GENERATED_QUESTION] : [];
  const router = createMemoryRouter(
    [
      { path: "/generate", element: <div data-testid="subject-select" /> },
      {
        path: "/generate/math",
        element: <GeneratePage subject="math" />,
      },
      { path: "/history", element: <div data-testid="history-page" /> },
    ],
    {
      initialEntries: ["/generate", "/generate/math"],
      initialIndex: 1,
    },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("GeneratePage browser Back guard", () => {
  it("navigates immediately when there is nothing to lose", async () => {
    const router = renderPage();

    await act(async () => {
      await router.navigate(-1);
    });

    expect(router.state.location.pathname).toBe("/generate");
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
  });

  it("blocks Back when there is unsubmitted input", async () => {
    const router = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));

    await act(async () => {
      await router.navigate(-1);
    });

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/generate/math");
  });

  it("blocks Back when generated questions are present", async () => {
    const router = renderPage({ withResults: true });

    await act(async () => {
      await router.navigate(-1);
    });

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
  });

  it("cancelling Back keeps the page and its content intact", async () => {
    const router = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));
    await act(async () => {
      await router.navigate(-1);
    });

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "confirm.destructive_cancel",
        }),
      );
    });

    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/generate/math");
    expect(screen.getByTestId("edit-form")).toBeInTheDocument();
  });

  it("blocks Back again after a previous Back was cancelled", async () => {
    const router = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));
    await act(async () => {
      await router.navigate(-1);
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "confirm.destructive_cancel",
      }),
    );
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();

    await act(async () => {
      await router.navigate(-1);
    });

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/generate/math");
  });

  it("completes Back navigation after confirmation", async () => {
    const router = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));
    await act(async () => {
      await router.navigate(-1);
    });

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "confirm.navigate_away_confirm",
        }),
      );
    });

    expect(router.state.location.pathname).toBe("/generate");
  });

  it("confirming an in-page exit does not ask a second time", async () => {
    const router = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "history.nav_link",
        }),
      );
    });

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "confirm.navigate_away_confirm",
        }),
      );
    });

    expect(router.state.location.pathname).toBe("/history");
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).toBeNull();
  });
});
