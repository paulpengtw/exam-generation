import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouteObject, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());
const fetchEventSourceMock = vi.hoisted(() =>
  vi.fn<(input: RequestInfo, init: FetchEventSourceInit) => Promise<void>>(),
);

vi.stubGlobal("__BUILD_ID__", "test-build-abc");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));
vi.mock("@sentry/react", () => ({ captureException: vi.fn() }));
vi.mock("../sentry", () => ({ isSentryEnabled: () => false }));
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    getSchemas: getSchemasMock,
    getAvailableModels: getAvailableModelsMock,
    planCoreQuestions: planCoreQuestionsMock,
    previewGenerate: previewGenerateMock,
    resolveGenerate: resolveGenerateMock,
  };
});
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "test"),
}));

import GeneratePage from "./GeneratePage";
import { useAuthStore } from "../store/authStore";
import { ReleaseState, useReleaseStore, resetReleaseDetector } from "../lib/release/releaseStore";
import { resetWorkspaceStoreForTests } from "../lib/workspace/workspaceStore";
import { resetRecoveryStoreForTests } from "../lib/recovery/recoveryStore";

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "推理", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  核心素養: [{ value: "A1", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

function setRelease(
  status: "current" | "unavailable",
  checkNow: () => Promise<void> = async () => {},
) {
  useReleaseStore.setState({
    status,
    requiredBuildId: null,
    releaseRevision: 1,
    supportedRecoveryFormats: [],
    lastCheckedAt: Date.now(),
    lastFailure: status === "unavailable" ? "http" : null,
    checkNow,
  } as ReleaseState);
}

function renderPage() {
  const routes: RouteObject[] = [
    { path: "/generate/math", element: <GeneratePage subject="math" /> },
  ];
  const router = createMemoryRouter(routes, {
    initialEntries: [{
      pathname: "/generate/math",
      state: {
        prefillParams: {
          grade: 7,
          count: 1,
          context: ["個人"],
          set_type: "單一題",
          q_type: ["選擇題"],
          content_type: "純文字",
          topic: "分數",
        },
      },
    }],
  });
  return render(<RouterProvider router={router} />);
}

describe("GeneratePage build-admission confirmation flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    resetReleaseDetector();
    resetRecoveryStoreForTests();
    resetWorkspaceStoreForTests();
    useAuthStore.setState({
      token: "token",
      user: { id: "user-1", email: "user@example.com", created_at: "2024-01-01T00:00:00Z" },
    });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: ["如何理解分數？"] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload: {
        ...payload,
        seed: 100,
        per_question_params: payload.per_question_params,
      },
      drawn: [],
      cleared: [],
    }));
    fetchEventSourceMock.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetReleaseDetector();
    resetRecoveryStoreForTests();
    resetWorkspaceStoreForTests();
  });

  it("shows a preflight error, keeps confirmation available, and retries after the policy recovers", async () => {
    setRelease("unavailable", async () => {
      setRelease("unavailable");
    });
    renderPage();

    const generateButton = await screen.findByRole("button", { name: /^(Generate|產生)$/i });
    await act(async () => {
      generateButton.click();
    });
    await screen.findByRole("heading", { name: /Review settings|發送前確認設定/i });
    const confirmButton = screen.getByRole("button", { name: /Confirm & Generate|確定發送/i });
    await waitFor(() => expect(confirmButton).not.toBeDisabled());

    await act(async () => {
      confirmButton.click();
    });

    expect(await screen.findByText("無法確認介面版本，請重新整理頁面後再試。"))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Review settings|發送前確認設定/i })).toBeInTheDocument();
    expect(confirmButton).not.toBeDisabled();
    expect(fetchEventSourceMock).not.toHaveBeenCalled();

    setRelease("current");
    await act(async () => {
      confirmButton.click();
    });

    await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalledOnce());
  });
});
