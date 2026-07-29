import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { FormParams } from "../components/ParamForm";
import type { GenerateStatus } from "../hooks/useGenerate";

const generateMock = vi.hoisted(() => vi.fn());
const resetMock = vi.hoisted(() => vi.fn());
const capturedSubmit = vi.hoisted(
  () => ({ current: null as ((params: FormParams) => void) | null }),
);

let configuredStatus: GenerateStatus = "idle";

const FIXED_PARAMS: FormParams = {
  grade: 7,
  count: 1,
  context: [],
  q_type: [],
  set_type: "",
  image_generation_mode: "html",
  skip_verify: false,
};

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: configuredStatus,
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    generate: generateMock,
    reset: resetMock,
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ state: null }),
  useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: {
    user: null;
    logout: () => void;
  }) => unknown) => selector({ user: null, logout: vi.fn() }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("../components/ParamForm", () => ({
  default: ({ onSubmit }: { onSubmit: (params: FormParams) => void }) => {
    capturedSubmit.current = onSubmit;
    return (
      <button
        type="button"
        data-testid="submit-form"
        onClick={() => capturedSubmit.current?.(FIXED_PARAMS)}
      >
        submit form
      </button>
    );
  },
}));

vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import GeneratePage from "./GeneratePage";

function renderPage(status: GenerateStatus) {
  configuredStatus = status;
  return render(<GeneratePage subject="math" />);
}

function submitForm() {
  fireEvent.click(screen.getByTestId("submit-form"));
}

function cancelResubmit() {
  fireEvent.click(
    screen.getByRole("button", { name: "confirm.destructive_cancel" }),
  );
}

function confirmResubmit() {
  fireEvent.click(
    screen.getByRole("button", { name: "confirm.resubmit_confirm" }),
  );
}

function expectOtherConfirmationsAbsent() {
  expect(
    screen.queryByText("confirm.navigate_away_title"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
  expect(
    screen.queryByText("confirm.clear_results_title"),
  ).not.toBeInTheDocument();
}

describe("GeneratePage resubmit guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configuredStatus = "idle";
    capturedSubmit.current = null;
  });

  it("submits immediately when no generation is running", () => {
    renderPage("idle");

    submitForm();

    expect(generateMock).toHaveBeenCalledOnce();
    expect(
      screen.queryByText("confirm.resubmit_title"),
    ).not.toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });

  it("confirms before starting a new generation while one is streaming", () => {
    renderPage("generating");

    submitForm();

    expect(screen.getByText("confirm.resubmit_title")).toBeInTheDocument();
    expect(generateMock).not.toHaveBeenCalled();
    expectOtherConfirmationsAbsent();
  });

  it("warns that the run in progress and its questions will be lost", () => {
    renderPage("generating");

    submitForm();

    expect(screen.getByText("confirm.resubmit_body")).toBeInTheDocument();
    expect(screen.getByText("confirm.resubmit_title")).toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });

  it("cancelling issues no new request", () => {
    renderPage("generating");
    submitForm();

    cancelResubmit();

    expect(generateMock).not.toHaveBeenCalled();
    expect(
      screen.queryByText("confirm.resubmit_title"),
    ).not.toBeInTheDocument();
  });

  it("cancelling leaves the running generation alive", () => {
    renderPage("generating");
    submitForm();

    cancelResubmit();

    // Issuing no new request leaves the in-flight run untouched: generate()
    // aborts the previous AbortController, so never calling it after cancel
    // proves that the original run remains alive.
    expect(generateMock).not.toHaveBeenCalled();
    expect(resetMock).not.toHaveBeenCalled();
  });

  it("confirming starts the new generation", () => {
    renderPage("generating");
    submitForm();

    confirmResubmit();

    expect(generateMock).toHaveBeenCalledOnce();
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining(FIXED_PARAMS),
    );
  });

  it("does not re-ask on a subsequent submit once nothing is running", () => {
    renderPage("idle");

    submitForm();
    expect(
      screen.queryByText("confirm.resubmit_title"),
    ).not.toBeInTheDocument();

    submitForm();

    expect(generateMock).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByText("confirm.resubmit_title"),
    ).not.toBeInTheDocument();
    expectOtherConfirmationsAbsent();
  });
});
