import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { GeneratedQuestion } from "../hooks/useGenerate";

const navigateMock = vi.hoisted(() => vi.fn());
const generateMock = vi.hoisted(() => vi.fn());
const resetMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

let configuredDisplayResults: GeneratedQuestion[] = [];

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useLocation: () => ({ state: null }),
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: [],
    displayResults: configuredDisplayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
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
  return render(<GeneratePage subject="math" />);
}

function clickEditForm() {
  fireEvent.click(screen.getByTestId("edit-form"));
}

function clickBackArrow() {
  fireEvent.click(screen.getByTitle("generate.btn_back_subjects"));
}

function clickHistory() {
  fireEvent.click(
    screen.getByRole("button", { name: "history.nav_link" }),
  );
}

function clickLogout() {
  fireEvent.click(
    screen.getByRole("button", { name: "generate.btn_logout" }),
  );
}

describe("GeneratePage navigation guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configuredDisplayResults = [];
  });

  it("navigates immediately from the back arrow on an untouched form with no results", () => {
    renderPage();

    clickBackArrow();

    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/generate");
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
  });

  it("navigates immediately from History on an untouched form with no results", () => {
    renderPage();

    clickHistory();

    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/history");
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
  });

  it("shows the modal from the back arrow once the form has been edited", () => {
    renderPage();
    clickEditForm();

    clickBackArrow();

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows the modal from History once the form has been edited", () => {
    renderPage();
    clickEditForm();

    clickHistory();

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows the modal from both buttons when generated questions exist even though the form was never edited", () => {
    renderPage({ withResults: true });

    clickBackArrow();

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.destructive_cancel" }),
    );
    clickHistory();

    expect(
      screen.getByText("confirm.navigate_away_title"),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("cancelling performs no navigation", () => {
    renderPage();
    clickEditForm();
    clickBackArrow();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.destructive_cancel" }),
    );

    expect(navigateMock).not.toHaveBeenCalled();
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
  });

  it("confirming navigates exactly once", () => {
    renderPage();
    clickEditForm();
    clickHistory();

    fireEvent.click(
      screen.getByRole("button", {
        name: "confirm.navigate_away_confirm",
      }),
    );

    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/history");
  });

  it("Esc cancels without navigating", () => {
    renderPage();
    clickEditForm();
    clickBackArrow();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(navigateMock).not.toHaveBeenCalled();
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
  });

  it("names the params when only unsubmitted input is present", () => {
    renderPage();
    clickEditForm();
    clickBackArrow();

    expect(
      screen.getByText("confirm.navigate_away_body_params"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.navigate_away_body_results"),
    ).not.toBeInTheDocument();
  });

  it("names the generated questions when only results are present", () => {
    renderPage({ withResults: true });
    clickBackArrow();

    expect(
      screen.getByText("confirm.navigate_away_body_results"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.navigate_away_body_params"),
    ).not.toBeInTheDocument();
  });

  it("names both when the form was edited and results exist", () => {
    renderPage({ withResults: true });
    clickEditForm();
    clickHistory();

    expect(
      screen.getByText("confirm.navigate_away_body_params"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("confirm.navigate_away_body_results"),
    ).toBeInTheDocument();
  });
});

describe("GeneratePage logout confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configuredDisplayResults = [];
  });

  it("always confirms logout, even on a pristine form", () => {
    renderPage();

    clickLogout();

    expect(screen.getByText("confirm.logout_title")).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("mentions only the session on a pristine generate page", () => {
    renderPage();

    clickLogout();

    expect(screen.getByText("confirm.logout_title")).toBeInTheDocument();
    expect(
      screen.getByText("confirm.logout_body_session"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.logout_body_work_lost"),
    ).not.toBeInTheDocument();
  });

  it("also warns about losing work when unsubmitted input is present", () => {
    renderPage();
    clickEditForm();

    clickLogout();

    expect(screen.getByText("confirm.logout_title")).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("confirm.logout_body_session"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("confirm.logout_body_work_lost"),
    ).toBeInTheDocument();
  });

  it("also warns about losing work when generated questions exist", () => {
    renderPage({ withResults: true });

    clickLogout();

    expect(screen.getByText("confirm.logout_title")).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.navigate_away_title"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("confirm.logout_body_session"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("confirm.logout_body_work_lost"),
    ).toBeInTheDocument();
  });

  it("cancelling logout does not log out, clear credentials or navigate", () => {
    renderPage();
    clickLogout();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.destructive_cancel" }),
    );

    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
    expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
  });

  it("confirming logout logs out and returns to the login page", () => {
    renderPage();
    clickLogout();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.logout_confirm" }),
    );

    expect(logoutMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/");
  });
});
