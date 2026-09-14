/**
 * Tests for ParamForm recovery restore — issue #772.
 * Written BEFORE the implementation (red phase).
 * Conservative: tests only that the recoveredForm prop is accepted and
 * that a recovery banner is shown when a form is recovered.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ParamForm from "./ParamForm";
import type { FormWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import { resetWorkspaceStoreForTests } from "../lib/workspace/workspaceStore";
import { useAuthStore } from "../store/authStore";

vi.stubGlobal("__BUILD_ID__", "dev-test");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

// Stub fetch for schemas endpoint
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: () =>
    Promise.resolve({
      學習階段: "第四學習階段",
      grades: [7, 8, 9],
      情境: [],
      題型種類: [],
      題型: [],
      數學思考: [],
      學習表現: [],
      學習內容: [],
    }),
}) as typeof fetch;

const RECOVERED_FORM: FormWorkspaceSnapshot = {
  kind: "form",
  version: 1,
  fields: {
    grade: 7,
    style: "",
    contentType: "純文字",
    customContentType: "",
    context: [],
    setType: "",
    qType: [],
    count: 1,
    coverageMode: "balanced",
    skipVerify: false,
    disableReferenceFewshot: false,
    coreQuestionCallback: true,
    imageGenerationMode: "gpt_image",
    difficulty: "",
    reportingScale: "",
    subjectFilter: "",
    passage: "",
    textWordLimit: null,
    textInstruction: "",
    options: ["", "", "", ""],
    topic: "",
    coreQuestion: null,
    subContext: "",
    scienceCompetency: [],
    learningPerformance: [],
    learningContent: [],
    subQuestionCount: "",
    subquestionConfigs: [],
    modelPlan: "",
    modelExecute: "",
    modelVerify: "",
    modelCorrect: "",
    effortPlan: "",
    effortExecute: "",
    effortVerify: "",
    effortCorrect: "",
    allowDuplicateFigureKinds: false,
  },
};

beforeEach(() => {
  resetWorkspaceStoreForTests();
  useAuthStore.setState({
    token: "tok",
    user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
  });
  localStorage.clear();
  sessionStorage.clear();
});

describe("ParamForm — recovery restore", () => {
  it("accepts recoveredForm prop without crashing", () => {
    expect(() =>
      render(
        <ParamForm
          subject="math"
          onSubmit={() => undefined}
          disabled={false}
          recoveredForm={RECOVERED_FORM}
        />,
      ),
    ).not.toThrow();
  });

  it("shows recovery banner when recoveredForm is provided", async () => {
    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM}
      />,
    );
    // Should show a banner about form restoration (may appear after initial render)
    await waitFor(() => {
      expect(
        screen.queryByText(/已還原更新前的表單|Form restored from before update/i),
      ).toBeInTheDocument();
    });
  });

  it("does not show recovery banner when recoveredForm is absent", () => {
    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
      />,
    );
    expect(
      screen.queryByText(/已還原更新前的表單|Form restored from before update/i),
    ).not.toBeInTheDocument();
  });
});
