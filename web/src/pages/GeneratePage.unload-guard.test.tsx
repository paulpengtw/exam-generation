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

describe("GeneratePage unload guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configuredDisplayResults = [];
    configuredStatus = "idle";
  });

  it("warns before closing the tab when 未送出的輸入 exist", () => {
    renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("does not warn before closing the tab when there is nothing to lose", () => {
    renderPage();

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("warns before closing the tab when generated questions exist", () => {
    renderPage({ withResults: true });

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("removes the handler when the page unmounts, so no prompt leaks onto other pages", () => {
    const { unmount } = renderPage();
    fireEvent.click(screen.getByTestId("edit-form"));
    unmount();

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });
});
