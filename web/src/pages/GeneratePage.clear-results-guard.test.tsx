import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type {
  GeneratedQuestion,
  GenerateStatus,
} from "../hooks/useGenerate";

const navigateMock = vi.hoisted(() => vi.fn());
const generateMock = vi.hoisted(() => vi.fn());
const resetMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

let configuredDisplayResults: GeneratedQuestion[] = [];
let configuredStatus: GenerateStatus = "idle";

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useLocation: () => ({ state: null }),
  useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: configuredStatus,
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

function renderPage({
  withResults = false,
  status = "idle",
}: {
  withResults?: boolean;
  status?: GenerateStatus;
} = {}) {
  configuredDisplayResults = withResults ? [GENERATED_QUESTION] : [];
  configuredStatus = status;
  return render(<GeneratePage subject="math" />);
}

function clickClear() {
  fireEvent.click(
    screen.getByRole("button", { name: "generate.btn_clear" }),
  );
}

function clickCancel() {
  fireEvent.click(
    screen.getByRole("button", { name: "confirm.destructive_cancel" }),
  );
}

function expectOtherConfirmationsAbsent() {
  expect(
    screen.queryByText("confirm.navigate_away_title"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
}

describe("GeneratePage clear results guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configuredDisplayResults = [];
    configuredStatus = "idle";
  });

  it("does not offer a clear control when there are no generated questions", () => {
    renderPage();

    expect(
      screen.queryByRole("button", { name: "generate.btn_clear" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("confirm.clear_results_title"),
    ).not.toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });

  it("confirms before clearing when generated questions exist", () => {
    renderPage({ withResults: true, status: "idle" });

    clickClear();

    expect(
      screen.getByText("confirm.clear_results_title"),
    ).toBeInTheDocument();
    expect(resetMock).not.toHaveBeenCalled();
    expectOtherConfirmationsAbsent();
  });

  it("warns only about clearing when nothing is streaming", () => {
    renderPage({ withResults: true, status: "idle" });

    clickClear();

    expect(
      screen.getByText("confirm.clear_results_body"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.clear_results_body_streaming"),
    ).not.toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });

  it("additionally warns that this page will stop showing a run still in progress", () => {
    renderPage({ withResults: true, status: "generating" });

    clickClear();

    expect(
      screen.getByText("confirm.clear_results_body"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("confirm.clear_results_body_streaming"),
    ).toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });

  it("cancelling leaves the generated questions in place", () => {
    renderPage({ withResults: true });
    clickClear();

    clickCancel();

    expect(resetMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "generate.btn_clear" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.clear_results_title"),
    ).not.toBeInTheDocument();
  });

  it("cancelling keeps watching a run still in progress", () => {
    renderPage({ withResults: true, status: "generating" });
    clickClear();

    clickCancel();

    // reset() is the only operation that stops watching the run locally, so not
    // calling it guarantees that the page keeps following it to completion.
    expect(resetMock).not.toHaveBeenCalled();
    expect(
      screen.queryByText("confirm.clear_results_title"),
    ).not.toBeInTheDocument();
  });

  it("confirming clears the questions and stops watching any in-flight run", () => {
    for (const status of ["idle", "generating"] satisfies GenerateStatus[]) {
      const { unmount } = renderPage({ withResults: true, status });
      clickClear();

      fireEvent.click(
        screen.getByRole("button", {
          name: "confirm.clear_results_confirm",
        }),
      );

      expect(resetMock).toHaveBeenCalledOnce();
      unmount();
      resetMock.mockClear();
    }
  });

  it("editing the form without generating does not bring up this modal", () => {
    renderPage();

    fireEvent.click(screen.getByTestId("edit-form"));

    expect(
      screen.queryByText("confirm.clear_results_title"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "generate.btn_clear" }),
    ).not.toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });
});
