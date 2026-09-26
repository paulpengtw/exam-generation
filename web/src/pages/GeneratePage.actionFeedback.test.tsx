import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const buildExamOdtMock = vi.hoisted(() => vi.fn());
const useGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/odt", () => ({
  buildExamOdt: buildExamOdtMock,
  formatTimestamp: () => "batch-test",
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: useGenerateMock,
}));

vi.mock("../lib/generationStream", () => ({
  projectGenerationCardEvidence: () => ({}),
  projectGenerationEvidence: () => null,
}));

vi.mock("../components/ParamForm", () => ({
  default: () => <div data-testid="param-form" />,
}));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/GenerationStatusBar", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: false, open: vi.fn() }),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { user: null; logoutExplicit: () => void }) => unknown) =>
    selector({ user: null, logoutExplicit: vi.fn() }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useLocation: () => ({ pathname: "/generate/math", state: null }),
    useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
  };
});

import GeneratePage from "./GeneratePage";

const question = (id: string) => ({
  id,
  情境: [],
  題型種類: "single",
  題型: "choice",
  題目: [`Question ${id}`],
  正確解題分析: ["Answer"],
});

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  buildExamOdtMock.mockReset();
  const first = question("proto-run-1-1");
  const second = question("proto-run-2-2");
  useGenerateMock.mockReturnValue({
    status: "done",
    progressLines: [],
    results: [first, second],
    displayResults: [
      { index: 0, question: first, phase: "verified", isFinal: true },
      { index: 1, question: second, phase: "verified", isFinal: true },
    ],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: 1,
    finishedAt: 2,
    generationLogId: null,
    subQuestionTotal: null,
    resultsCompletion: "complete",
    terminalEvidence: false,
    evidence: null,
    generate: vi.fn(),
    restoreResults: vi.fn(),
    reset: vi.fn(),
  });
});

describe("GeneratePage export feedback", () => {
  it("reports one named group for a partial batch ODT failure without creating a file", async () => {
    buildExamOdtMock.mockRejectedValueOnce({ questionIndex: 1 });
    const createObjectUrl = vi.spyOn(URL, "createObjectURL");

    render(
      <MemoryRouter initialEntries={["/generate/math"]}>
        <Routes>
          <Route path="/generate/math" element={<GeneratePage subject="math" />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(
      "Group #2 (proto-run-2-2): unable to generate the ODT file.",
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Download all as ODT/i })).toHaveAttribute(
      "data-action-state",
      "failed",
    );
    expect(buildExamOdtMock).toHaveBeenCalledOnce();
    expect(createObjectUrl).not.toHaveBeenCalled();

    await waitFor(() => expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument());
    createObjectUrl.mockRestore();
  });
});
