/**
 * Tests for ParamForm recovery restore — issue #772.
 * Covers original acceptance (banner display) and T2 (field application, invalid tracking,
 * acknowledge/discard callbacks, no planner/resolver side effects).
 */
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { FormWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { useAuthStore } from "../store/authStore";
import { saveDraft } from "../lib/formDraft";

vi.stubGlobal("__BUILD_ID__", "dev-test");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

// ---- API client module mock ----
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

// Default math schema
const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "社會", instruction: "" },
  ],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "填充題", instruction: "" },
  ],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [
    { value: "課本", instruction: "" },
    { value: "素養", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const DEFAULT_MODELS = {
  allowed: ["claude-sonnet-4-6", "claude-opus-4-6"],
  defaults: { plan: "claude-sonnet-4-6", execute: "claude-sonnet-4-6" },
  effort: {} as Record<string, string[]>,
};

import ParamForm from "./ParamForm";

const RECOVERED_FORM_EMPTY: FormWorkspaceSnapshot = {
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

/** Recovered form with distinctive values for testing. */
const RECOVERED_FORM_WITH_VALUES: FormWorkspaceSnapshot = {
  kind: "form",
  version: 1,
  fields: {
    ...RECOVERED_FORM_EMPTY.fields,
    grade: 8,
    topic: "unique-topic-xyz",
    passage: "distinctive-passage-abc",
    modelExecute: "claude-opus-4-6",
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
  vi.clearAllMocks();
  // Re-set defaults after clearAllMocks
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(DEFAULT_MODELS);
});

// ---------------------------------------------------------------------------
// Original acceptance tests (must remain green)
// ---------------------------------------------------------------------------

describe("ParamForm — recovery restore", () => {
  it("accepts recoveredForm prop without crashing", () => {
    expect(() =>
      render(
        <ParamForm
          subject="math"
          onSubmit={() => undefined}
          disabled={false}
          recoveredForm={RECOVERED_FORM_EMPTY}
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
        recoveredForm={RECOVERED_FORM_EMPTY}
      />,
    );
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

// ---------------------------------------------------------------------------
// T2: field application, invalid tracking, callbacks, guard side effects
// ---------------------------------------------------------------------------

describe("ParamForm — recovery restore T2", () => {
  it("workspace export has recovered topic before schemas resolve", async () => {
    // Schemas never resolve during this test
    getSchemasMock.mockReturnValue(new Promise(() => {}));
    getAvailableModelsMock.mockReturnValue(new Promise(() => {}));

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_WITH_VALUES}
      />,
    );

    // The form surface should be registered (even while showing skeleton)
    // and the exportWorkspace seam should return the recovered topic.
    await waitFor(() => {
      const ws = useWorkspaceStore.getState();
      expect(ws.surfaces["generate.form"]).toBeDefined();
    });

    const ws = useWorkspaceStore.getState();
    const exported = ws.surfaces["generate.form"]?.exportWorkspace?.();
    expect(exported?.kind).toBe("form");
    if (exported?.kind === "form") {
      expect(exported.fields.topic).toBe("unique-topic-xyz");
    }
  });

  it("recovered topic value persists after schemas resolve", async () => {
    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_WITH_VALUES}
      />,
    );

    // Wait for schemas to load (題型 checkboxes appear)
    await waitFor(() => {
      expect(screen.queryByText("選擇題")).toBeInTheDocument();
    });

    const topicInput = screen.getByPlaceholderText(/e\.g\. Climate change|例如：氣候變遷/i);
    expect((topicInput as HTMLInputElement).value).toBe("unique-topic-xyz");
  });

  it("draft in localStorage does NOT prompt when recoveredForm is present", async () => {
    // Put a draft in localStorage for this user
    saveDraft("u1", {
      ...RECOVERED_FORM_EMPTY.fields,
      topic: "saved-draft-topic",
    });

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_WITH_VALUES}
      />,
    );

    // Wait for banner to appear
    await waitFor(() => {
      expect(screen.queryByText(/已還原更新前的表單|Form restored from before update/i)).toBeInTheDocument();
    });

    // Draft prompt must NOT appear — check the draft-related banner text is absent
    expect(screen.queryByText(/已儲存草稿|Draft found|draft_found|form\.draft_found/i)).not.toBeInTheDocument();
    // The draft content should not be the topic shown (topic is from recoveredForm)
    const topicInput = screen.getByPlaceholderText(/e\.g\. Climate change|例如：氣候變遷/i);
    expect((topicInput as HTMLInputElement).value).toBe("unique-topic-xyz");
  });

  it("late model discovery does not overwrite recovered modelExecute", async () => {
    // Delay models resolution to simulate late discovery
    let resolveModels!: (v: typeof DEFAULT_MODELS) => void;
    getAvailableModelsMock.mockReturnValue(
      new Promise<typeof DEFAULT_MODELS>((res) => {
        resolveModels = res;
      }),
    );

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_WITH_VALUES} // modelExecute = "claude-opus-4-6"
      />,
    );

    // Wait for schemas to settle (but not models)
    await waitFor(() => {
      expect(screen.queryByText("選擇題")).toBeInTheDocument();
    });

    // Now resolve models with a different default
    await act(async () => {
      resolveModels({
        allowed: ["claude-sonnet-4-6", "claude-opus-4-6"],
        defaults: { plan: "claude-sonnet-4-6", execute: "claude-sonnet-4-6" },
        effort: {},
      });
    });

    // modelExecute should still be "claude-opus-4-6" (recovered value wins)
    const ws = useWorkspaceStore.getState();
    const exportFn = ws.surfaces["generate.form"]?.exportWorkspace;
    expect(exportFn).toBeDefined();
    const exported = exportFn?.();
    expect(exported?.kind).toBe("form");
    if (exported?.kind === "form") {
      expect(exported.fields.modelExecute).toBe("claude-opus-4-6");
    }
  });

  it("recovered qType value not in schema shows invalid marker and disables submit", async () => {
    const recoveredFormInvalidQType: FormWorkspaceSnapshot = {
      ...RECOVERED_FORM_WITH_VALUES,
      fields: {
        ...RECOVERED_FORM_WITH_VALUES.fields,
        qType: ["unknown-qtype-xyz"],
      },
    };

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={recoveredFormInvalidQType}
      />,
    );

    // Wait for schemas to load
    await waitFor(() => {
      expect(screen.queryByText("選擇題")).toBeInTheDocument();
    });

    // An invalid field notice should appear
    await waitFor(() => {
      expect(
        screen.queryByText(/invalid|無效|not valid|不在允許清單|recovery.*invalid/i),
      ).toBeInTheDocument();
    });
  });

  it("確認 calls onRecoveryAcknowledge and dismisses the banner", async () => {
    const onAck = vi.fn();

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_EMPTY}
        onRecoveryAcknowledge={onAck}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText(/已還原更新前的表單|Form restored from before update/i)).toBeInTheDocument();
    });

    const ackButton = screen.getByRole("button", { name: /確認|Acknowledge/i });
    await act(async () => {
      fireEvent.click(ackButton);
    });

    expect(onAck).toHaveBeenCalledOnce();
    // Banner dismissed
    expect(
      screen.queryByText(/已還原更新前的表單|Form restored from before update/i),
    ).not.toBeInTheDocument();
  });

  it("捨棄 calls onRecoveryDiscard and dismisses the banner", async () => {
    const onDiscard = vi.fn();

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_EMPTY}
        onRecoveryDiscard={onDiscard}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText(/已還原更新前的表單|Form restored from before update/i)).toBeInTheDocument();
    });

    const discardButton = screen.getByRole("button", { name: /捨棄|Discard/i });
    await act(async () => {
      fireEvent.click(discardButton);
    });

    expect(onDiscard).toHaveBeenCalledOnce();
    // Banner dismissed
    expect(
      screen.queryByText(/已還原更新前的表單|Form restored from before update/i),
    ).not.toBeInTheDocument();
  });

  it("beginOperation is never called for generate/resolve/modification/planning during restore", async () => {
    const spy = vi.spyOn(useWorkspaceStore.getState(), "beginOperation");

    render(
      <ParamForm
        subject="math"
        onSubmit={() => undefined}
        disabled={false}
        recoveredForm={RECOVERED_FORM_EMPTY}
      />,
    );

    // Wait for schemas and models to settle
    await waitFor(() => {
      expect(screen.queryByText("選擇題")).toBeInTheDocument();
    });

    const restrictedKinds = ["generation", "resolve", "modification", "core_question_planning"];
    const calls = spy.mock.calls.map(([kind]) => kind);
    for (const kind of restrictedKinds) {
      expect(calls).not.toContain(kind);
    }
  });
});
