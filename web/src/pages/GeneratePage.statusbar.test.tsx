import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const generateState = vi.hoisted(() => ({
  status: "idle" as "idle" | "generating" | "error",
  progressLines: [] as string[],
  results: [] as unknown[],
  displayResults: [] as unknown[],
  llmCalls: [] as unknown[],
  startedAt: null as number | null,
  finishedAt: null as number | null,
  subQuestionTotal: null as number | null,
}));

const statusBar = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

const paramForm = vi.hoisted(() => ({
  renders: 0,
  onSubmit: null as ((p: Record<string, unknown>) => void) | null,
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: generateState.status,
    progressLines: generateState.progressLines,
    results: generateState.results,
    displayResults: generateState.displayResults,
    llmCalls: generateState.llmCalls,
    agentLanes: [],
    errorMessage: null,
    startedAt: generateState.startedAt,
    finishedAt: generateState.finishedAt,
    subQuestionTotal: generateState.subQuestionTotal,
    generate: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("../components/GenerationStatusBar", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../components/GenerationStatusBar")>();
  return {
    ...actual,
    default: (props: Parameters<typeof actual.default>[0]) => {
      statusBar.props = { ...props };
      const ActualStatusBar = actual.default;
      return <ActualStatusBar {...props} />;
    },
  };
});

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ state: null }),
  useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: null; logout: () => void }) => unknown) =>
    selector({ user: null, logout: vi.fn() }),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: true, open: vi.fn() }),
}));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("../components/ParamForm", () => ({
  default: ({ onSubmit }: { onSubmit: (p: Record<string, unknown>) => void }) => {
    paramForm.renders += 1;
    paramForm.onSubmit = onSubmit;
    return <div data-testid="param-form" />;
  },
}));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import GeneratePage from "./GeneratePage";

describe("GeneratePage — 生成進度列", () => {
  beforeEach(() => {
    generateState.status = "idle";
    generateState.progressLines = [];
    generateState.results = [];
    generateState.displayResults = [];
    generateState.llmCalls = [];
    generateState.startedAt = null;
    generateState.finishedAt = null;
  });

  it.each(["math", "social_studies", "natural_sciences"] as const)(
    "docks the 生成進度列 to 生成頁面 for %s",
    (subject) => {
      render(<GeneratePage subject={subject} />);

      expect(screen.getByLabelText("生成進度列")).toBeInTheDocument();
      expect(screen.getByTestId("statusbar-status")).toHaveTextContent(
        "尚未生成",
      );
    },
  );
});

describe("GeneratePage — 生成進度列 section jumps", () => {
  beforeEach(() => {
    generateState.status = "idle";
    generateState.progressLines = ["第 1 題 開始生成"];
    generateState.results = [];
    generateState.displayResults = [];
    generateState.llmCalls = [];
    generateState.startedAt = null;
    generateState.finishedAt = null;
  });

  it("scrolls to 進度 when the 進度 target is used", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    render(<GeneratePage subject="math" />);

    fireEvent.click(screen.getByRole("button", { name: "進度" }));

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
  });

  it("keeps 結果 inert until a run has produced something", () => {
    render(<GeneratePage subject="math" />);

    expect(screen.getByRole("button", { name: "結果" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "進度" })).toBeEnabled();
  });
});

describe("GeneratePage — 生成進度列 elapsed timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    generateState.status = "generating";
    generateState.progressLines = ["第 1 題 開始生成"];
    generateState.results = [];
    generateState.displayResults = [];
    generateState.llmCalls = [];
    generateState.startedAt = 0;
    generateState.finishedAt = null;
    paramForm.renders = 0;
    paramForm.onSubmit = null;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks the elapsed time without re-rendering the rest of the page", () => {
    render(<GeneratePage subject="math" />);

    expect(screen.getByTestId("statusbar-elapsed")).toHaveTextContent("0秒");
    const rendersBeforeTicking = paramForm.renders;

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(screen.getByTestId("statusbar-elapsed")).toHaveTextContent("5秒");
    expect(paramForm.renders).toBe(rendersBeforeTicking);
  });
});

describe("GeneratePage — 生成步驟 wiring", () => {
  beforeEach(() => {
    generateState.status = "idle";
    generateState.progressLines = [];
    generateState.results = [];
    generateState.displayResults = [];
    generateState.llmCalls = [
      {
        type: "stage",
        agent: "sub_generator#1",
        stage: "llm_generate",
        status: "start",
        ts: 1_000,
      },
    ];
    generateState.startedAt = 1_000;
    generateState.finishedAt = null;
    generateState.subQuestionTotal = null;
    paramForm.onSubmit = null;
    statusBar.props = null;
  });

  it("uses the announced 子題 total when the form omitted 子題數", () => {
    const page = render(<GeneratePage subject="social_studies" />);

    act(() => {
      paramForm.onSubmit?.({ count: 1 });
    });
    generateState.status = "generating";
    generateState.subQuestionTotal = 5;
    page.rerender(<GeneratePage subject="social_studies" />);

    expect(statusBar.props).toEqual(
      expect.objectContaining({
        subject: "social_studies",
        stageEvents: generateState.llmCalls,
        subQuestionCount: 5,
      }),
    );
  });

  it("keeps the submitted 子題 count when a different total is announced", () => {
    const page = render(<GeneratePage subject="social_studies" />);

    act(() => {
      paramForm.onSubmit?.({ count: 1, sub_question_count: 4 });
    });
    generateState.status = "generating";
    generateState.subQuestionTotal = 5;
    page.rerender(<GeneratePage subject="social_studies" />);

    expect(statusBar.props).toEqual(
      expect.objectContaining({
        subject: "social_studies",
        stageEvents: generateState.llmCalls,
        subQuestionCount: 4,
      }),
    );
  });
});
