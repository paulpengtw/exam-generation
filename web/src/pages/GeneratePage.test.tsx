import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

// --- mock useGenerate ---
const generateMock = vi.fn();
vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    generate: generateMock,
    reset: vi.fn(),
  }),
}));

// --- mock router ---
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ state: null }),
}));

// --- mock authStore ---
vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: null; logout: () => void }) => unknown) =>
    selector({ user: null, logout: vi.fn() }),
}));

// --- mock i18n ---
vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

// --- mock odt ---
vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

// --- mock ParamForm: captures onSubmit so tests can call it directly ---
let capturedOnSubmit: ((p: Record<string, unknown>) => void) | null = null;
vi.mock("../components/ParamForm", () => ({
  default: ({ onSubmit }: { onSubmit: (p: Record<string, unknown>) => void }) => {
    capturedOnSubmit = onSubmit;
    return <div data-testid="param-form" />;
  },
}));

// --- mock leaf components ---
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import GeneratePage from "./GeneratePage";

// Minimal form params that satisfy ParamForm's GenerateParams interface
const BASE_PARAMS: Record<string, unknown> = {
  grade: 7,
  count: 1,
  context: [],
  q_type: [],
  set_type: "",
  image_generation_mode: "html",
  skip_verify: false,
};

describe("GeneratePage — handleSubmit forwards params to generate()", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedOnSubmit = null;
  });

  it("forwards difficulty to generate()", () => {
    render(<GeneratePage subject="math" />);
    capturedOnSubmit!({ ...BASE_PARAMS, difficulty: "hard" });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ difficulty: "hard" }),
    );
  });

  it("omits difficulty when not set in form params", () => {
    render(<GeneratePage subject="math" />);
    capturedOnSubmit!({ ...BASE_PARAMS });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ difficulty: undefined }),
    );
  });

  it("forwards coverage_mode for social_studies", () => {
    render(<GeneratePage subject="social_studies" />);
    capturedOnSubmit!({ ...BASE_PARAMS, coverage_mode: "random" });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ coverage_mode: "random" }),
    );
  });

  it("omits coverage_mode when subject is math", () => {
    render(<GeneratePage subject="math" />);
    capturedOnSubmit!({ ...BASE_PARAMS, coverage_mode: "balanced" });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ coverage_mode: undefined }),
    );
  });

  it("forwards per_question_params from the confirmed form payload", () => {
    const perQuestionParams = JSON.stringify([
      { subject: "math", grade: 7, learning_performance: ["n-IV-1"] },
    ]);

    render(<GeneratePage subject="math" />);
    capturedOnSubmit!({ ...BASE_PARAMS, per_question_params: perQuestionParams });

    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ per_question_params: perQuestionParams }),
    );
  });

  it("forwards text_word_limit to generate()", () => {
    render(<GeneratePage subject="social_studies" />);
    capturedOnSubmit!({ ...BASE_PARAMS, text_word_limit: 500 });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ text_word_limit: 500 }),
    );
  });

  it("forwards subject_filter as a 1-element string[] when a value is set", () => {
    render(<GeneratePage subject="social_studies" />);
    capturedOnSubmit!({ ...BASE_PARAMS, subject_filter: "歷史" });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ subject_filter: ["歷史"] }),
    );
  });

  it("passes subject_filter as undefined when the form sends undefined", () => {
    render(<GeneratePage subject="social_studies" />);
    capturedOnSubmit!({ ...BASE_PARAMS, subject_filter: undefined });
    expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({ subject_filter: undefined }),
    );
  });
});
