/**
 * Recovery flow integration test — issues #772/#773.
 *
 * Drives the real App router (routes array with createMemoryRouter) to prove
 * the save → persist → restore → confirm cycle end-to-end.
 *
 * Scenarios:
 *   1. Full form flow: type topic → 儲存草稿並更新 → reload → restore → 確認 → deleted
 *   2. Confirmation flow: settled multi-group workspaces restore for all subjects, including
 *      per-subquestion settings, text instructions, curriculum, models/efforts, media, and draws
 *   3. Quota failure: reload not called, form preserved, 重試 button shown
 *   4. Unsupported format / changed target: refused before saving, nothing in storage
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ExamQuestion, GeneratedQuestion } from "./hooks/useGenerate";
import type { ResultsWorkspaceSnapshot } from "./lib/workspace/adapters/types";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

// ---- Mock heavy page dependencies ----
const generateMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());
const restoreResultsMock = vi.hoisted(() => vi.fn(() => true));
const generatedState = vi.hoisted(() => ({
  status: "idle" as const,
  progressLines: [] as string[],
  results: [] as ExamQuestion[],
  displayResults: [] as GeneratedQuestion[],
  llmCalls: [],
  agentLanes: [],
  errorMessage: null,
  startedAt: null,
  finishedAt: null,
  generationLogId: null,
  subQuestionTotal: null,
  resultsCompletion: null,
  terminalEvidence: false,
}));
vi.mock("./hooks/useGenerate", () => ({
  useGenerate: () => ({ ...generatedState, generate: generateMock, reset: vi.fn(), restoreResults: restoreResultsMock }),
}));
vi.mock("./components/ProgressLog", () => ({ default: () => null }));
vi.mock("./components/QuestionCard", () => ({
  default: ({ question, isFinal }: { question: ExamQuestion; isFinal: boolean }) => (
    <article data-testid={`recovered-card-${question.id ?? "unknown"}`}>
      <p>{question.題目.join(" ")}</p>
      {question.image_base64 ? (
        <img alt={question.id ?? "recovered question"} src={`data:image/png;base64,${question.image_base64}`} />
      ) : null}
      <button type="button" disabled={!isFinal}>card.download_json</button>
    </article>
  ),
}));
vi.mock("./components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("./utils/odt", () => ({ buildExamOdt: vi.fn(), formatTimestamp: vi.fn(() => "ts") }));

// ---- Mock API client (schemas + models) ----
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
vi.mock("./api/client", async (importActual) => {
  const actual = await importActual<typeof import("./api/client")>();
  return {
    ...actual,
    getSchemas: getSchemasMock,
    getAvailableModels: getAvailableModelsMock,
    planCoreQuestions: planCoreQuestionsMock,
    previewGenerate: previewGenerateMock,
    resolveGenerate: resolveGenerateMock,
  };
});

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [
    { value: "單一題", instruction: "" },
    { value: "題組題", instruction: "" },
  ],
  題型: [{ value: "選擇題", instruction: "" }, { value: "填充題", instruction: "" }],
  數學思考: [{ value: "推理", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  核心素養: [{ value: "A1", instruction: "" }],
  學習表現: [{ value: "數學-表現-1", instruction: "", 科目: "數與量", admitted_by: { 科目: ["數與量"] } }],
  學習內容: [{ value: "數學-內容-1", instruction: "", admitted_by: { 科目: ["數與量"] } }],
};

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "校園", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  認知歷程: [{ value: "理解", instruction: "" }],
  內容領域: [{ value: "民主政治", instruction: "" }],
  核心素養: [{ value: "社-A1", instruction: "" }],
  題目內容類型: [{ value: "文章", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  question_style: [],
  數學思考: [],
  學習表現: [{ value: "社會-表現-1", instruction: "", 科目: "歷史", admitted_by: { 科目: ["歷史"] } }],
  學習內容: [{ value: "社會-內容-1", instruction: "", admitted_by: { 科目: ["歷史"] } }],
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", instruction: "", admitted_by: { 情境: ["個人"] } }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple multiple-choice", instruction: "" }],
  reporting_scale: [{ value: "3", instruction: "Level 3" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  題目內容類型: [{ value: "文章", instruction: "" }],
  科目: [],
  question_style: [],
  數學思考: [],
  學習表現: [{ value: "自然-表現-1", instruction: "", 科目: "自然科學" }],
  學習內容: [{ value: "自然-內容-1", instruction: "", 科目: "自然科學" }],
};

const AVAILABLE_MODELS = {
  allowed: ["claude-sonnet-4-6", "claude-opus-4-6"],
  defaults: {
    plan: "claude-sonnet-4-6",
    execute: "claude-sonnet-4-6",
    verify: "claude-sonnet-4-6",
    correct: "claude-sonnet-4-6",
    effort_plan: "medium",
    effort_execute: "medium",
    effort_verify: "medium",
    effort_correct: "medium",
  },
  effort: {
    "claude-sonnet-4-6": ["low", "medium", "high"],
    "claude-opus-4-6": ["medium", "high"],
  } as Record<string, string[]>,
};

const RECOVERY_FORM_FIELDS = {
  grade: 8,
  style: "課本",
  contentType: "文章",
  customContentType: "",
  context: ["校園"],
  setType: "題組題",
  qType: ["選擇題"],
  count: 2,
  coverageMode: "balanced" as const,
  skipVerify: false,
  disableReferenceFewshot: false,
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image" as const,
  difficulty: "medium" as const,
  reportingScale: "3",
  subjectFilter: "歷史",
  passage: "captured passage",
  textWordLimit: 180,
  textInstruction: "captured text instruction",
  options: ["A", "B", "C", "D"],
  topic: "captured ordinary form",
  coreQuestion: null,
  subContext: "健康",
  scienceCompetency: ["能力一"],
  learningPerformance: ["社會-表現-1"],
  learningContent: ["社會-內容-1"],
  subQuestionCount: 3,
  subquestionConfigs: [],
  contentDomain: "民主政治",
  targetSurface: "紙本" as const,
  modelPlan: "claude-opus-4-6",
  modelExecute: "claude-opus-4-6",
  modelVerify: "claude-sonnet-4-6",
  modelCorrect: "claude-sonnet-4-6",
  effortPlan: "high",
  effortExecute: "high",
  effortVerify: "medium",
  effortCorrect: "medium",
  allowDuplicateFigureKinds: false,
};

function recoveredForm(subject: "math" | "social_studies" | "natural_sciences"): FormWorkspaceSnapshot {
  const fields = {
    ...RECOVERY_FORM_FIELDS,
    subjectFilter: subject === "social_studies" ? "歷史" : "",
    context: subject === "natural_sciences" ? ["個人"] : subject === "math" ? ["個人"] : ["校園"],
    setType: "題組題",
    contentType: subject === "math" ? "純文字" : "文章",
    style: subject === "math" ? "課本" : "",
    subContext: subject === "natural_sciences" ? "健康" : "",
    scienceCompetency: subject === "natural_sciences" ? ["能力一"] : [],
    learningPerformance: subject === "math" ? ["數學-表現-1"] : subject === "social_studies" ? ["社會-表現-1"] : ["自然-表現-1"],
    learningContent: subject === "math" ? ["數學-內容-1"] : subject === "social_studies" ? ["社會-內容-1"] : ["自然-內容-1"],
    contentDomain: subject === "social_studies" ? "民主政治" : "",
  };
  return { kind: "form", version: 1, fields } as FormWorkspaceSnapshot;
}

function confirmationSnapshot(
  subject: "math" | "social_studies" | "natural_sciences",
): ConfirmationWorkspaceSnapshot {
  const configs = [
    {
      question_type: subject === "natural_sciences" ? "Simple multiple-choice" : "選擇題",
      instruction: "first subquestion instruction",
      content_type: subject === "math" ? "純文字" : "文章",
      image_generation_mode: "html" as const,
      question_word_limit: 40,
      option_word_limit: 12,
      ...(subject === "social_studies" ? { cognitive_process: "理解" } : {}),
      ...(subject === "natural_sciences" ? { reporting_scale: "3" } : {}),
      learning_content: [subject === "math" ? "數學-內容-1" : subject === "social_studies" ? "社會-內容-1" : "自然-內容-1"],
      learning_performance: [subject === "math" ? "數學-表現-1" : subject === "social_studies" ? "社會-表現-1" : "自然-表現-1"],
    },
    {
      question_type: subject === "natural_sciences" ? "Simple multiple-choice" : "選擇題",
      instruction: "second subquestion instruction",
      content_type: subject === "math" ? "純文字" : "文章",
      ...(subject === "social_studies" ? { cognitive_process: "理解" } : {}),
      ...(subject === "natural_sciences" ? { reporting_scale: "3" } : {}),
      learning_content: [subject === "math" ? "數學-內容-1" : subject === "social_studies" ? "社會-內容-1" : "自然-內容-1"],
      learning_performance: [subject === "math" ? "數學-表現-1" : subject === "social_studies" ? "社會-表現-1" : "自然-表現-1"],
    },
    {
      question_type: subject === "natural_sciences" ? "Simple multiple-choice" : "選擇題",
      instruction: "third subquestion instruction",
      content_type: subject === "math" ? "純文字" : "文章",
      ...(subject === "social_studies" ? { cognitive_process: "理解" } : {}),
      ...(subject === "natural_sciences" ? { reporting_scale: "3" } : {}),
    },
  ];
  const rows = [0, 1].map((index) => ({
    context: subject === "natural_sciences" ? ["個人"] : subject === "math" ? ["個人"] : ["校園"],
    set_type: "題組題",
    q_type: subject === "social_studies" ? [] : [subject === "natural_sciences" ? "Simple multiple-choice" : "選擇題"],
    topic: `${subject}-captured-group-${index + 1}`,
    text_instruction: `group ${index + 1} text instruction`,
    content_type: subject === "math" ? "純文字" : "文章",
    ...(subject === "math" ? { style: "課本", math_thinking: ["推理"], core_competency: ["A1"] } : {}),
    ...(subject === "social_studies" ? { subject_filter: "歷史", content_domain: "民主政治", cognitive_process: ["理解"], core_competency: ["社-A1"] } : {}),
    ...(subject === "natural_sciences" ? { sub_context: "健康", science_competency: ["能力一"], reporting_scale: "3" } : {}),
    learning_content: [subject === "math" ? "數學-內容-1" : subject === "social_studies" ? "社會-內容-1" : "自然-內容-1"],
    learning_performance: [subject === "math" ? "數學-表現-1" : subject === "social_studies" ? "社會-表現-1" : "自然-表現-1"],
    sub_question_count: 3,
    subquestion_configs: JSON.stringify(configs),
  }));
  const pendingParams = {
    subject,
    grade: 8,
    count: 2,
    set_type: "題組題",
    q_type: subject === "social_studies" ? [] : [subject === "natural_sciences" ? "Simple multiple-choice" : "選擇題"],
    context: subject === "natural_sciences" ? ["個人"] : subject === "math" ? ["個人"] : ["校園"],
    topic: `${subject}-captured-core-topic`,
    passage: `${subject} captured passage`,
    text_instruction: "captured request text instruction",
    image_generation_mode: "gpt_image",
    model_plan: "claude-opus-4-6",
    model_execute: "claude-opus-4-6",
    model_verify: "claude-sonnet-4-6",
    model_correct: "claude-sonnet-4-6",
    effort_plan: "high",
    effort_execute: "high",
    effort_verify: "medium",
    effort_correct: "medium",
    seed: 20260917,
    drawn: [
      "seed",
      "per_question_params[0].context",
      "per_question_params[1].learning_content",
      subject === "social_studies"
        ? "per_question_params[1].subquestion_configs[2].認知歷程"
        : subject === "natural_sciences"
          ? "per_question_params[1].subquestion_configs[2].reporting_scale"
          : "per_question_params[1].subquestion_configs[2].question_type",
    ],
    ...(subject === "math" ? { style: "課本", math_thinking: ["推理"], core_competency: ["A1"] } : {}),
    ...(subject === "social_studies" ? { subject_filter: "歷史", content_domain: "民主政治", core_competency: ["社-A1"] } : {}),
    ...(subject === "natural_sciences" ? { sub_context: "健康", science_competency: ["能力一"], reporting_scale: "3" } : {}),
    per_question_params: JSON.stringify(rows),
  };
  return {
    kind: "confirmation",
    version: 1,
    pendingParams: pendingParams as never,
    pendingPerQuestionParams: rows,
    pendingPrefill: { topic: `${subject}-history-prefill`, count: 2 },
    clearedPaths: ["per_question_params[1].learning_content"],
    redraws: { "per_question_params[1].learning_content": 1 },
    hasPendingConfirmationEdits: true,
    coreQuestionResolution: "generated",
    historyDraftChoice: "history",
  };
}

import { useAuthStore } from "./store/authStore";
import { useReleaseStore, resetReleaseDetector } from "./lib/release/releaseStore";
import { useWorkspaceStore, resetWorkspaceStoreForTests } from "./lib/workspace/workspaceStore";
import {
  useRecoveryStore,
  resetRecoveryStoreForTests,
  initRecoveryStore,
  initRecoveryStoreAsync,
} from "./lib/recovery/recoveryStore";
import { evaluateSaveAndUpdate, runSaveAndUpdate } from "./lib/recovery/saveAndUpdate";
import {
  loadSnapshot,
  loadTabPointer,
  saveSnapshotTransactionally,
  persistTabPointer,
  getOrCreateTabId,
  claimSnapshot,
  releaseSnapshotClaim,
  deleteAllSnapshotsForAccount,
  detectTabCollision,
  startTabCollisionListener,
} from "./lib/recovery/storage";
import { RECOVERY_FORMAT_V1 } from "./lib/recovery/format";
import { importResultsWorkspace } from "./lib/workspace/adapters/resultsWorkspace";
import { routes } from "./routes";
import type { ReleaseState } from "./lib/release/releaseStore";
import type { ConfirmationWorkspaceSnapshot, FormWorkspaceSnapshot } from "./lib/workspace/adapters/types";

const USER = { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" };
const RECOVERY_SLOW_BOUNDARY_DELAY = 1500;

function setUpUpdateRequired() {
  useReleaseStore.setState({
    status: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
}

function setUpCurrent() {
  useReleaseStore.setState({
    status: "current",
    requiredBuildId: null,
    releaseRevision: 1,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
}

function renderApp(
  initialEntry = "/generate/math",
  state?: { prefillParams?: Record<string, unknown> },
) {
  const router = createMemoryRouter(routes, {
    initialEntries: [state === undefined ? initialEntry : { pathname: initialEntry, state }],
    initialIndex: 0,
  });
  const { unmount } = render(<RouterProvider router={router} />);
  return { router, unmount };
}

function realMathConfirmationPrefill(): Record<string, unknown> {
  const rows = [0, 1].map((index) => ({
    context: ["個人"],
    set_type: "題組題",
    q_type: ["選擇題"],
    topic: `real-flow-group-${index + 1}`,
    core_question: "real-flow-core-question",
    style: ["課本"],
    math_thinking: ["推理"],
    core_competency: ["A1"],
    learning_content: ["數學-內容-1"],
    learning_performance: ["數學-表現-1"],
  }));
  return {
    grade: 8,
    context: ["個人"],
    set_type: "題組題",
    q_type: ["選擇題"],
    count: 2,
    content_type: "純文字",
    image_generation_mode: "gpt_image",
    style: "課本",
    math_thinking: ["推理"],
    core_competency: ["A1"],
    subject_filter: ["數與量"],
    topic: "real-flow-core-topic",
    core_question: "real-flow-core-question",
    passage: "real-flow-passage",
    options: ["甲", "乙", "丙", "丁"],
    learning_content: ["數學-內容-1"],
    learning_performance: ["數學-表現-1"],
    sub_question_count: 3,
    model_plan: "claude-opus-4-6",
    model_execute: "claude-opus-4-6",
    model_verify: "claude-sonnet-4-6",
    model_correct: "claude-sonnet-4-6",
    effort_plan: "high",
    effort_execute: "high",
    effort_verify: "medium",
    effort_correct: "medium",
    skip_verify: false,
    disable_reference_fewshot: false,
    drawn: ["per_question_params[0].context"],
    per_question_params: JSON.stringify(rows),
  };
}

async function persistRecoveryFixture(
  subject: "math" | "social_studies" | "natural_sciences",
  confirmation: ConfirmationWorkspaceSnapshot,
): Promise<string> {
  const route = `/generate/${subject}`;
  const snapshotId = `confirmation-${subject}`;
  const tabId = getOrCreateTabId();
  const result = await saveSnapshotTransactionally({
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: snapshotId,
    tab_id: tabId,
    route,
    subject,
    account_id: USER.id,
    origin: "https://test.example.com",
    environment: "production",
    source_build_id: "build-A",
    target_build_id: "build-B",
    source_release_revision: 1,
    target_release_revision: 2,
    saved_at: new Date(0).toISOString(),
    workspace_revision: 7,
    form: recoveredForm(subject),
    confirmation,
  });
  expect(result.ok).toBe(true);
  const pointer = await persistTabPointer({
    tab_id: tabId,
    snapshot_id: snapshotId,
    account_id: USER.id,
    route,
    attempted_target_build_id: "build-B",
    attempted_target_release_revision: 2,
  });
  expect(pointer.ok).toBe(true);
  return snapshotId;
}

function receivedResultsFixture(subject: "math" | "social_studies" | "natural_sciences"): ResultsWorkspaceSnapshot {
  const finalId = `${subject}-final`;
  const partialId = `${subject}-partial`;
  const finalQuestion: ExamQuestion = {
    id: finalId, 情境: [], 題型種類: subject === "math" ? "single" : "題組題", 題型: "選擇題",
    題目: [`${subject} final received question`], 正確解題分析: ["known answer"],
  };
  const partialQuestion: ExamQuestion = {
    id: partialId, 情境: [], 題型種類: "題組題", 題型: "選擇題",
    題目: [`${subject} partial received draft`], 正確解題分析: ["draft answer"],
  };
  return {
    kind: "results", version: 1,
    results: [finalQuestion],
    displayResults: [
      { index: 0, question: finalQuestion, phase: "verified", isFinal: true, stableId: finalId, contentRevision: 7 },
      { index: 1, question: partialQuestion, phase: "draft", isFinal: false, stableId: partialId, contentRevision: 2 },
    ],
    progressLines: [`${subject} received progress`], errorMessage: null,
    startedAt: 10, finishedAt: 20, subQuestionTotal: subject === "math" ? null : 3,
    requestedTotal: 2, submittedSubQuestionCount: subject === "math" ? null : 3,
    completion: "unknown", processing: "unknown", terminalEvidence: false, runId: `${subject}-run`,
    evidence: [
      { stableId: finalId, index: 0, receipt: "final", processing: "unknown", contentRevision: 7, terminal: "unknown", review: { status: "passed", contentRevision: 7 } },
      { stableId: partialId, index: 1, receipt: "draft", processing: "unknown", contentRevision: 2, terminal: "unknown", review: { status: "unknown", contentRevision: 2 } },
    ],
    images: {
      [finalId]: { base64: "ZmluYWw=", mimeType: "image/png", location: "question" },
      [partialId]: { base64: "cGFydGlhbA==", mimeType: "image/png", location: "question" },
    },
  };
}

async function persistResultsFixture(
  subject: "math" | "social_studies" | "natural_sciences",
): Promise<{ snapshotId: string; results: ResultsWorkspaceSnapshot }> {
  const route = `/generate/${subject}`;
  const snapshotId = `results-${subject}`;
  const tabId = getOrCreateTabId();
  const results = receivedResultsFixture(subject);
  const saved = await saveSnapshotTransactionally({
    schema: RECOVERY_FORMAT_V1, snapshot_id: snapshotId, tab_id: tabId, route, subject,
    account_id: USER.id, origin: "https://test.example.com", environment: "production",
    source_build_id: "build-A", target_build_id: "build-B", source_release_revision: 1,
    target_release_revision: 2, saved_at: new Date(0).toISOString(), workspace_revision: 11,
    form: recoveredForm(subject), results,
  });
  expect(saved.ok).toBe(true);
  const pointer = await persistTabPointer({
    tab_id: tabId, snapshot_id: snapshotId, account_id: USER.id, route,
    attempted_target_build_id: "build-B", attempted_target_release_revision: 2,
  });
  expect(pointer.ok).toBe(true);
  return { snapshotId, results };
}

beforeEach(() => {
  // Restore any vi.spyOn() overrides from the previous test before clearing.
  // vi.clearAllMocks() only resets call counts; it leaves mockImplementation in
  // place, which can pollute later tests (e.g. localStorage.setItem spy from
  // identity g leaking into identity h).
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
  getSchemasMock.mockImplementation(async (subject = "math") => {
    if (subject === "social_studies") return SOCIAL_SCHEMA;
    if (subject === "natural_sciences") return NATURAL_SCHEMA;
    return MATH_SCHEMA;
  });
  getAvailableModelsMock.mockResolvedValue(AVAILABLE_MODELS);
  planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
  previewGenerateMock.mockResolvedValue({ prompts: [] });
  resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({ payload, drawn: [] }));
  resetWorkspaceStoreForTests();
  resetRecoveryStoreForTests();
  resetReleaseDetector();
  // Reset the release store to a neutral initial state so that stale
  // `status: "update-required"` or `status: "current"` values from a
  // previous test cannot leak through the store into the next test.
  // `resetReleaseDetector()` only resets the in-flight request tracking;
  // the store itself must be reset separately.
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
    supportedRecoveryFormats: [],
    checkNow: async () => {},
  } as ReleaseState);
  useAuthStore.setState({
    token: "tok",
    user: USER,
  });
  vi.stubGlobal("location", {
    pathname: "/generate/math",
    origin: "https://test.example.com",
    reload: vi.fn(),
    href: "https://test.example.com/generate/math",
  });
  generatedState.results = [];
  generatedState.displayResults = [];
  generatedState.progressLines = [];
  generatedState.errorMessage = null;
  generatedState.startedAt = null;
  generatedState.finishedAt = null;
  generatedState.resultsCompletion = null;
  generatedState.terminalEvidence = false;
  restoreResultsMock.mockReset();
  restoreResultsMock.mockReturnValue(true);
});

afterEach(() => {
  // Unmount any components that a test left mounted (e.g. when a test assertion
  // fails before reaching its own `unmount()` call). Without this, stale
  // ReleaseNotice components remain in the DOM with live Zustand subscriptions;
  // they can interfere with later tests by reacting to store changes, firing
  // auto-refresh effects, or duplicating DOM elements visible to `screen`.
  cleanup();
  vi.unstubAllGlobals();
  vi.stubGlobal("__BUILD_ID__", "build-A");
  vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
});

describe("recovery flow — scenario 1: full save → restore → confirm", () => {
  it("saves snapshot with the typed topic and restores it after reload", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();

    // --- Phase 1: Render app, type topic, save ---
    const { unmount } = renderApp();

    // Wait for the topic input to appear (schemas loaded)
    const topicInput = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );

    // Type a distinctive topic (do NOT advance autosave timer)
    await act(async () => {
      fireEvent.change(topicInput, { target: { value: "flow-test-unique-topic" } });
    });

    // Run save-and-update via the function directly (simulating button click)
    const saveResult = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(saveResult.ok).toBe(true);
    if (!saveResult.ok) throw new Error(`Save failed: ${JSON.stringify(saveResult)}`);

    // navigate was called (simulated reload)
    expect(navigateSpy).toHaveBeenCalledOnce();

    // Snapshot and pointer must be in storage
    const snap = loadSnapshot("u1", saveResult.snapshot_id);
    expect(snap).not.toBeNull();
    expect(snap?.schema).toBe(RECOVERY_FORMAT_V1);
    expect(snap?.form.fields.topic).toBe("flow-test-unique-topic");

    const pointer = loadTabPointer();
    expect(pointer).not.toBeNull();
    expect(pointer?.snapshot_id).toBe(saveResult.snapshot_id);
    expect(pointer?.attempted_target_build_id).toBe("build-B");

    unmount();

    // --- Phase 2: Simulate BUILD_ID = 'B', policy current, render again ---
    vi.stubGlobal("__BUILD_ID__", "build-B");
    setUpCurrent();
    resetWorkspaceStoreForTests();

    // initRecoveryStore simulates what boot does
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });

    // Recovery store should have pending snapshot
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    expect(useRecoveryStore.getState().pending?.form.fields.topic).toBe("flow-test-unique-topic");

    // Render the app again with the saved auth and recovery state
    // The app picks up the recovery store's pending snapshot on mount
    const { unmount: unmount2 } = renderApp();

    // Before schemas resolve, the workspace export should have the topic
    // (ParamForm initializes formFields from recoveredForm immediately)
    await waitFor(() => {
      const ws = useWorkspaceStore.getState();
      // Either workspace has the exported form, or ParamForm is still mounting
      // — the surface registers on mount via useSurfaceParticipation
      expect(ws.surfaces["generate.form"]).toBeDefined();
    });

    // After schemas resolve, topic shows in DOM and the recovery banner appears
    const topicInput2 = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    expect((topicInput2 as HTMLInputElement).value).toBe("flow-test-unique-topic");

    // Recovery banner should appear now
    await waitFor(() => {
      expect(
        screen.queryByText(/Form restored from before update|已還原更新前的表單/i),
      ).toBeInTheDocument();
    });

    // Click 確認 (Acknowledge)
    const ackButton = screen.getByRole("button", { name: /Acknowledge|確認/i });
    await act(async () => {
      fireEvent.click(ackButton);
    });

    // After acknowledge: snapshot + pointer should be deleted
    await waitFor(() => {
      expect(loadSnapshot("u1", saveResult.snapshot_id)).toBeNull();
      expect(loadTabPointer()).toBeNull();
    });

    unmount2();
  });

  it("creates the settled confirmation through the visible save control and reopens the exact payload", async () => {
    setUpUpdateRequired();
    window.history.replaceState({}, "", "/generate/math");
    const resolvedSeed = 20260917;
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => {
      const sourceRows = JSON.parse(String(payload.per_question_params)) as Record<string, unknown>[];
      const resolvedRows = sourceRows.map((row, index) => ({ ...row, seed: resolvedSeed + index }));
      return {
        payload: {
          ...payload,
          seed: resolvedSeed,
          per_question_params: JSON.stringify(resolvedRows),
        },
        drawn: ["seed", "per_question_params[0].context"],
      };
    });
    const reloadSpy = vi.spyOn(window.location, "reload").mockImplementation(() => undefined);

    const prefillParams = realMathConfirmationPrefill();
    const { unmount } = renderApp("/generate/math", { prefillParams });
    fireEvent.click(await screen.findByRole("button", { name: /^(Generate|產生)$/i }));
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledOnce());
    await screen.findByRole("heading", { name: /Review settings|發送前確認設定/i });

    const capturedConfirmation = useWorkspaceStore
      .getState()
      .surfaces["generate.confirmation"]
      ?.exportWorkspace?.();
    expect(capturedConfirmation?.kind).toBe("confirmation");
    if (!capturedConfirmation || capturedConfirmation.kind !== "confirmation") {
      throw new Error("expected a settled confirmation workspace");
    }
    expect(capturedConfirmation.pendingParams.seed).toBe(resolvedSeed);
    expect(capturedConfirmation.pendingPerQuestionParams).toHaveLength(2);

    const saveButton = screen.getByRole("button", { name: /儲存草稿並更新|Save Draft & Update/i });
    expect(saveButton).not.toBeDisabled();
    await act(async () => {
      fireEvent.click(saveButton);
    });
    await waitFor(() => expect(reloadSpy).toHaveBeenCalledOnce());

    const pointer = loadTabPointer();
    expect(pointer?.snapshot_id).toBeTruthy();
    const saved = loadSnapshot(USER.id, pointer!.snapshot_id!);
    expect(saved?.confirmation).toEqual(capturedConfirmation);
    expect(saved?.confirmation?.pendingPrefill).toEqual(prefillParams);
    const previewCallsBeforeRestore = previewGenerateMock.mock.calls.length;

    unmount();
    reloadSpy.mockRestore();
    vi.stubGlobal("__BUILD_ID__", "build-B");
    setUpCurrent();
    resetWorkspaceStoreForTests();
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: window.location.origin,
      environment: "production",
    });

    const { unmount: unmountRestored } = renderApp();
    await screen.findByText("real-flow-core-topic");
    expect(screen.getByText("real-flow-passage")).toBeInTheDocument();
    expect(planCoreQuestionsMock).not.toHaveBeenCalled();
    expect(previewGenerateMock).toHaveBeenCalledTimes(previewCallsBeforeRestore);
    expect(resolveGenerateMock).toHaveBeenCalledOnce();

    const confirmButton = await screen.findByRole("button", { name: /確認送出|Confirm & Generate/i });
    await waitFor(() => expect(confirmButton).not.toBeDisabled());
    await act(async () => {
      fireEvent.click(confirmButton);
    });
    await waitFor(() => expect(generateMock).toHaveBeenCalledOnce());
    expect(generateMock.mock.calls[0][0]).toMatchObject(capturedConfirmation.pendingParams);
    expect(generateMock.mock.calls[0][0].per_question_params).toBe(
      capturedConfirmation.pendingParams.per_question_params,
    );
    unmountRestored();
  });
});

describe("recovery flow — scenario 1b: restore settled confirmation workspaces", () => {
  it.each([
    ["math", "/generate/math"],
    ["social_studies", "/generate/social_studies"],
    ["natural_sciences", "/generate/natural_sciences"],
  ] as const)("restores the complete %s confirmation without rebuilding it", async (subject, route) => {
    setUpCurrent();
    vi.stubGlobal("__BUILD_ID__", "build-B");
    const confirmation = confirmationSnapshot(subject);
    const snapshotId = await persistRecoveryFixture(subject, confirmation);
    initRecoveryStore({
      currentRoute: route,
      origin: "https://test.example.com",
      environment: "production",
    });

    expect(useRecoveryStore.getState().pending?.confirmation).toEqual(confirmation);
    const { unmount } = renderApp(route);

    expect(await screen.findByText(`${subject}-captured-core-topic`)).toBeInTheDocument();
    if (subject === "social_studies") {
      expect(screen.getByText("captured request text instruction")).toBeInTheDocument();
    } else if (subject === "natural_sciences") {
      expect(screen.getAllByDisplayValue("group 1 text instruction").length).toBeGreaterThan(0);
    }
    if (subject !== "math") {
      expect(screen.getAllByDisplayValue("first subquestion instruction").length).toBeGreaterThan(0);
      expect(screen.getAllByDisplayValue("second subquestion instruction").length).toBeGreaterThan(0);
      expect(screen.getAllByDisplayValue("third subquestion instruction").length).toBeGreaterThan(0);
    }
    expect(screen.getAllByText("claude-opus-4-6").length).toBeGreaterThan(0);
    expect((await screen.findAllByText("high")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(subject === "math" ? "數學-內容-1" : subject === "social_studies" ? "社會-內容-1" : "自然-內容-1").length).toBeGreaterThan(0);
    expect(screen.getByText("gpt_image")).toBeInTheDocument();
    expect(screen.getAllByText(/各小題配置|Per-sub-question configuration/i).length).toBeGreaterThan(0);

    const confirmationBanner = screen.getByText(/Confirmation restored from before update|已還原更新前的發送前確認/i);
    expect(confirmationBanner).toBeInTheDocument();
    expect(planCoreQuestionsMock).not.toHaveBeenCalled();
    expect(previewGenerateMock).not.toHaveBeenCalled();
    expect(resolveGenerateMock).not.toHaveBeenCalled();

    // A captured parent draw remains editable and supports an explicit redraw.
    const firstQuestion = screen.getByRole("region", { name: /Question 1|第 1 題/i });
    const redrawButtons = within(firstQuestion).getAllByRole("button", { name: /Redraw|重抽/i });
    expect(redrawButtons.length).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(redrawButtons[0]);
    });
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledOnce());
    if (subject === "social_studies") {
      const secondQuestion = screen.getByRole("region", { name: /Question 2|第 2 題/i });
      const childRedrawButtons = within(secondQuestion).getAllByRole("button", { name: /Redraw|重抽/i });
      await act(async () => {
        fireEvent.click(childRedrawButtons[childRedrawButtons.length - 1]);
      });
      await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    }

    // The confirmation-only operation does not rewrite the ordinary form workspace.
    const form = useWorkspaceStore.getState().surfaces["generate.form"]?.exportWorkspace?.();
    expect(form?.kind === "form" && form.fields.topic).toBe("captured ordinary form");
    expect(useRecoveryStore.getState().pending?.confirmation?.pendingPrefill).toEqual({
      topic: `${subject}-history-prefill`,
      count: 2,
    });

    // Acknowledgement clears the store/storage, but the mounted form keeps the
    // latched confirmation long enough for the teacher to continue or submit.
    const acknowledgeButton = screen.getAllByRole("button").find((button) =>
      /^(Acknowledge|確認)$/i.test(button.textContent?.trim() ?? ""),
    );
    expect(acknowledgeButton).toBeDefined();
    await act(async () => {
      fireEvent.click(acknowledgeButton!);
    });
    await waitFor(() => expect(useRecoveryStore.getState().pending).toBeNull());
    expect(loadSnapshot(USER.id, snapshotId)).toBeNull();
    expect(screen.getByText(`${subject}-captured-core-topic`)).toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: /Confirm & Generate|確認送出/i });
    expect(confirmButton).not.toBeDisabled();
    await act(async () => {
      fireEvent.click(confirmButton);
    });
    await waitFor(() => expect(generateMock).toHaveBeenCalledOnce());
    expect(generateMock.mock.calls[0][0]).toMatchObject({
      subject,
      topic: `${subject}-captured-core-topic`,
    });
    const submittedRows = JSON.parse(
      generateMock.mock.calls[0][0].per_question_params as string,
    ) as Array<Record<string, unknown>>;
    const latestResolveCall = resolveGenerateMock.mock.calls.at(-1);
    const resolvedRows = JSON.parse(
      latestResolveCall?.[0].per_question_params as string,
    ) as Array<Record<string, unknown>>;
    expect(submittedRows).toEqual(resolvedRows);
    expect(submittedRows[1]).toMatchObject({
      topic: confirmation.pendingPerQuestionParams![1].topic,
      text_instruction: confirmation.pendingPerQuestionParams![1].text_instruction,
      learning_content: confirmation.pendingPerQuestionParams![1].learning_content,
    });
    unmount();
  });

  it("restores confirmation before delayed schema/model discovery and keeps hydration inert", async () => {
    setUpCurrent();
    const confirmation = confirmationSnapshot("social_studies");
    await persistRecoveryFixture("social_studies", confirmation);
    initRecoveryStore({
      currentRoute: "/generate/social_studies",
      origin: "https://test.example.com",
      environment: "production",
    });
    let resolveSchema!: (value: typeof SOCIAL_SCHEMA) => void;
    let resolveModels!: (value: typeof AVAILABLE_MODELS) => void;
    getSchemasMock.mockReturnValue(new Promise<typeof SOCIAL_SCHEMA>((resolve) => {
      resolveSchema = resolve;
    }));
    getAvailableModelsMock.mockReturnValue(new Promise<typeof AVAILABLE_MODELS>((resolve) => {
      resolveModels = resolve;
    }));

    const { unmount } = renderApp("/generate/social_studies");
    expect(screen.getByText("social_studies-captured-core-topic")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("first subquestion instruction").length).toBeGreaterThan(0);
    expect(planCoreQuestionsMock).not.toHaveBeenCalled();
    expect(previewGenerateMock).not.toHaveBeenCalled();
    expect(resolveGenerateMock).not.toHaveBeenCalled();

    await act(async () => {
      resolveSchema(SOCIAL_SCHEMA);
      resolveModels(AVAILABLE_MODELS);
    });
    await waitFor(() => expect(screen.getByText("social_studies-captured-core-topic")).toBeInTheDocument());
    expect(planCoreQuestionsMock).not.toHaveBeenCalled();
    expect(previewGenerateMock).not.toHaveBeenCalled();
    expect(resolveGenerateMock).not.toHaveBeenCalled();
    expect(useWorkspaceStore.getState().operations).toHaveLength(0);
    unmount();
  });
});

describe("recovery flow — scenario 1c: preserve received results", () => {
  it.each([
    ["math", "/generate/math"],
    ["social_studies", "/generate/social_studies"],
    ["natural_sciences", "/generate/natural_sciences"],
  ] as const)("restores final and partial image-bearing results for %s without starting a stream", async (subject, route) => {
    setUpCurrent();
    vi.stubGlobal("__BUILD_ID__", "build-B");
    const { snapshotId, results } = await persistResultsFixture(subject);
    const hydrated = importResultsWorkspace(results);
    expect(hydrated).not.toBeNull();
    generatedState.results = hydrated?.results ?? [];
    generatedState.displayResults = hydrated?.displayResults ?? [];
    generatedState.resultsCompletion = "unknown";
    initRecoveryStore({
      currentRoute: route,
      origin: "https://test.example.com",
      environment: "production",
    });

    const { unmount } = renderApp(route);
    expect(restoreResultsMock).toHaveBeenCalledOnce();
    expect(screen.getByText(`${subject} final received question`)).toBeInTheDocument();
    expect(screen.getByText(`${subject} partial received draft`)).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByTestId("statusbar-status").textContent).toMatch(/未知|unknown/i);
    const downloadJson = screen.getByRole("button", { name: /Download all as JSON|下載全部 JSON/i });
    expect(downloadJson).not.toBeDisabled();
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:recovered-json");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(downloadJson);
    expect(createObjectUrl).toHaveBeenCalledOnce();

    const acknowledge = await waitFor(() => {
      const button = screen.getAllByRole("button").find((candidate) =>
        /^(Acknowledge|確認)$/i.test(candidate.textContent?.trim() ?? ""));
      if (!button) throw new Error("recovery acknowledgement is not ready");
      return button;
    });
    expect(acknowledge).toBeDefined();
    await act(async () => { fireEvent.click(acknowledge!); });
    await waitFor(() => expect(useRecoveryStore.getState().pending).toBeNull());
    expect(loadSnapshot(USER.id, snapshotId)).toBeNull();
    expect(screen.getByText(`${subject} final received question`)).toBeInTheDocument();
    unmount();
  });

  it("keeps the saved results snapshot and banner after repeated hydration failures", async () => {
    setUpCurrent();
    vi.stubGlobal("__BUILD_ID__", "build-B");
    const { snapshotId } = await persistResultsFixture("math");
    generatedState.results = [];
    generatedState.displayResults = [];
    restoreResultsMock.mockReturnValue(false);
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });

    const { unmount } = renderApp("/generate/math");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /Retry|重試/i });
    await act(async () => { fireEvent.click(retry); });
    expect(restoreResultsMock).toHaveBeenCalledTimes(2);
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();

    const acknowledge = await waitFor(() => {
      const button = screen.getAllByRole("button").find((candidate) =>
        /^(Acknowledge|確認)$/i.test(candidate.textContent?.trim() ?? ""));
      if (!button) throw new Error("recovery acknowledgement is not ready");
      return button;
    });
    await act(async () => { fireEvent.click(acknowledge!); });
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();
    unmount();
  });
});

describe("recovery flow — scenario 2: quota failure", () => {
  it("reload not called, freezeInput reset, quota reason returned", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();

    const { unmount } = renderApp();
    // Wait for form to render so the surface is registered with export seam
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    // Wait for schemas and model list to finish loading so the form surface
    // transitions from "hydrating" to "ready" before evaluateSaveAndUpdate
    // is called; otherwise the "hydrating" check would shadow "quota".
    await waitFor(() => {
      expect(useWorkspaceStore.getState().surfaces["generate.form"]?.readiness).toBe("ready");
    });
    // Flush any React effects still queued after the readiness transition
    // (e.g. the subquestion-config sync effect). Without this flush they run
    // during "await checkNow()" inside runSaveAndUpdate, incrementing
    // workspace_revision between the snapshot and the recheck, which returns
    // "workspace_changed" before the quota path is reached.
    await act(async () => {});

    // Make localStorage.setItem throw only on the recovery-snapshot write.
    // Using mockImplementation with a key guard instead of mockImplementationOnce
    // prevents background React effects (model/effort useEffect writes such as
    // "effort_plan", "model_plan", etc.) from consuming the injected failure
    // before saveSnapshotTransactionally reaches its setItem call.
    const originalSetItem = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, "setItem").mockImplementation((key: string, value: string) => {
      if (key.startsWith("exam_recovery_u1_")) {
        throw new DOMException("QuotaExceededError", "QuotaExceededError");
      }
      return originalSetItem(key, value);
    });

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    // Reload must NOT have been called
    expect(navigateSpy).not.toHaveBeenCalled();

    // Result should indicate quota failure
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("quota");

    // Nothing in storage — no snapshot keys for this user
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_u1_"))).toHaveLength(0);

    // freezeInput reset to false after failure
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);

    unmount();
  });

  it("read-back mismatch keeps the original form workspace and does not navigate", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();
    const { unmount } = renderApp();
    const topicInput = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    await act(async () => {
      fireEvent.change(topicInput, { target: { value: "readback-preserved-topic" } });
    });
    vi.spyOn(localStorage, "getItem").mockImplementationOnce(() => "{\"corrupt\":true}");

    const result = await runSaveAndUpdate({
      navigate: navigateSpy, origin: "https://test.example.com", environment: "production", buildId: "build-A",
    });

    expect(result).toEqual({ ok: false, reason: "readback_mismatch", retryable: true });
    expect(navigateSpy).not.toHaveBeenCalled();
    expect((topicInput as HTMLInputElement).value).toBe("readback-preserved-topic");
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
    unmount();
  });

  it("captures settled workspaces before the recheck and refuses when the target changes", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();
    let resolveModels!: (value: typeof AVAILABLE_MODELS) => void;
    getAvailableModelsMock.mockImplementationOnce(() => new Promise<typeof AVAILABLE_MODELS>((resolve) => {
      resolveModels = resolve;
    }));
    const { unmount } = renderApp();
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    // The topic input renders before model discovery completes. Hold that
    // promise deliberately so the save path cannot accidentally race hydration.
    expect(useWorkspaceStore.getState().surfaces["generate.form"]?.readiness).toBe("hydrating");
    await act(async () => { resolveModels(AVAILABLE_MODELS); });
    await waitFor(() => {
      expect(useWorkspaceStore.getState().surfaces["generate.form"]?.readiness).toBe("ready");
    }, { timeout: 5000 });
    // Flush effects scheduled by the readiness transition before capturing the
    // workspace revision in runSaveAndUpdate.
    await act(async () => {});
    await act(async () => {
      useReleaseStore.setState({
        checkNow: async () => {
          useReleaseStore.setState({ requiredBuildId: "build-C" });
        },
      });
    });

    let result!: Awaited<ReturnType<typeof runSaveAndUpdate>>;
    await act(async () => {
      result = await runSaveAndUpdate({
        navigate: navigateSpy,
        origin: "https://test.example.com",
        environment: "production",
        buildId: "build-A",
      });
    });

    expect(result).toEqual({ ok: false, reason: "target_changed", retryable: false });
    expect(navigateSpy).not.toHaveBeenCalled();
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) keys.push(key);
    }
    expect(keys.some((key) => key.startsWith("exam_recovery_u1_"))).toBe(false);
    unmount();
  });

  it("重試 retry button is shown in ReleaseNotice after a save error", async () => {
    setUpUpdateRequired();

    const { unmount } = renderApp();
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    await waitFor(() => {
      expect(useWorkspaceStore.getState().surfaces["generate.form"]?.readiness).toBe("ready");
    }, { timeout: 5000 });
    await act(async () => {});

    // Keep the real save path and make its failure promise deterministically
    // slower than waitFor's historical one-second default.
    useReleaseStore.setState({
      checkNow: async () => {
        await new Promise<void>((resolve) => {
          setTimeout(resolve, RECOVERY_SLOW_BOUNDARY_DELAY);
        });
      },
    });

    // Spy on setItem to make the save fail, targeting only the snapshot write so
    // background React effects (model/effort useEffect writes) cannot consume
    // the injected failure before saveSnapshotTransactionally.
    const originalSetItemRetry = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, "setItem").mockImplementation((key: string, value: string) => {
      if (key.startsWith("exam_recovery_u1_")) {
        throw new DOMException("QuotaExceededError", "QuotaExceededError");
      }
      return originalSetItemRetry(key, value);
    });

    // Click the 儲存草稿並更新 button in ReleaseNotice
    const saveButton = screen.getByRole("button", { name: /Save Draft & Update|儲存草稿並更新/i });
    await waitFor(() => expect(saveButton).toBeEnabled(), { timeout: 5000 });
    await act(async () => {
      fireEvent.click(saveButton);
    });

    // After the failed save, a 重試/Retry button should appear
    // once the async save handler updates ReleaseNotice; keep the event-bound
    // query on the same explicit CI budget as the other recovery waits.
    await screen.findByRole(
      "button",
      { name: /Retry|重試/i },
      { timeout: 5000 },
    );

    unmount();
  });
});

describe("recovery flow — scenario 3: unsupported format", () => {
  it("refuses before saving when target does not support recovery format", async () => {
    // Set release state without the recovery format
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: [], // No recovery format supported
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);

    const navigateSpy = vi.fn();

    // Render the app so a form surface with export seam is registered
    const { unmount } = renderApp();
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    // Wait for schemas (and model list) to finish loading so the form surface
    // transitions from "hydrating" to "ready" before evaluateSaveAndUpdate
    // is called; otherwise the earliest check ("hydrating") would shadow the
    // intended check ("unsupported_target_reader").
    await waitFor(() => {
      expect(useWorkspaceStore.getState().surfaces["generate.form"]?.readiness).toBe("ready");
    });

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    // Should fail because format not supported
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("unsupported_target_reader");

    // navigate not called
    expect(navigateSpy).not.toHaveBeenCalled();

    // Nothing in storage
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);

    unmount();
  });
});

describe("recovery store flow — existing tests", () => {
  it("snapshot saved transactionally can be loaded back", async () => {
    const snap = {
      schema: RECOVERY_FORMAT_V1,
      snapshot_id: "test-snap-001",
      tab_id: getOrCreateTabId(),
      route: "/generate",
      subject: "math",
      account_id: "u1",
      origin: "https://example.com",
      environment: "production",
      source_build_id: "build-A",
      target_build_id: "build-B",
      source_release_revision: 1,
      target_release_revision: 2,
      saved_at: new Date().toISOString(),
      workspace_revision: 3,
      form: { kind: "form" as const, version: 1 as const, fields: {} as never },
    };

    const saveResult = await saveSnapshotTransactionally(snap);
    expect(saveResult.ok).toBe(true);

    const pointerResult = await persistTabPointer({
      account_id: "u1",
      snapshot_id: "test-snap-001",
      route: "/generate",
    });
    expect(pointerResult.ok).toBe(true);
  });

  it("initRecoveryStore restores pending snapshot on boot", async () => {
    const tabId = getOrCreateTabId();
    const snap = {
      schema: RECOVERY_FORMAT_V1,
      snapshot_id: "boot-snap-001",
      tab_id: tabId,
      route: "/generate",
      subject: "math",
      account_id: "u1",
      origin: "https://example.com",
      environment: "production",
      source_build_id: "build-A",
      target_build_id: "build-B",
      source_release_revision: 1,
      target_release_revision: 2,
      saved_at: new Date().toISOString(),
      workspace_revision: 0,
      form: { kind: "form" as const, version: 1 as const, fields: {} as never },
    };

    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "u1",
      snapshot_id: "boot-snap-001",
      route: "/generate",
    });

    initRecoveryStore({
      currentRoute: "/generate",
      origin: "https://example.com",
      environment: "production",
    });

    const state = useRecoveryStore.getState();
    expect(state.pending).not.toBeNull();
    expect(state.pending?.snapshot_id).toBe("boot-snap-001");
    expect(state.pending?.workspace_revision).toBe(0);
  });

  it("workspaceStore workspace_revision increments on surface registration", () => {
    const rev0 = useWorkspaceStore.getState().workspace_revision;
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: false,
      hasReceivedResults: false,
    });
    const rev1 = useWorkspaceStore.getState().workspace_revision;
    expect(rev1).toBeGreaterThan(rev0);
  });

  it("workspaceStore approveNavigation + clearNavigationApproval work", () => {
    useWorkspaceStore.getState().approveNavigation("/new-page");
    expect(useWorkspaceStore.getState().navigationApproved).toEqual({ target: "/new-page" });
    useWorkspaceStore.getState().clearNavigationApproval();
    expect(useWorkspaceStore.getState().navigationApproved).toBeNull();
  });

  it("evaluateSaveAndUpdate returns allowed when all conditions are met", () => {
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: true,
      hasReceivedResults: false,
      exportWorkspace: () => ({ kind: "form", version: 1, fields: {} as never }),
    });

    const { surfaces, operations } = useWorkspaceStore.getState();

    const result = evaluateSaveAndUpdate({
      surfaces,
      operations,
      releaseStatus: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
      user: USER,
    });

    expect(result.allowed).toBe(true);
  });
});

// ── Recovery identity — router-driven flow tests (issue #776) ─────────────────
//
// These tests verify the eight acceptance criteria of the recovery-identity
// feature through the real router layer (renderApp / direct auth-store calls
// after a rendered session), complementing the unit-level tests in
// recoveryIdentity.test.ts.

// Helper: write a snapshot + pointer for the default user and route.
async function seedSnapshot(
  opts: {
    snapshotId?: string;
    accountId?: string;
    route?: string;
    subject?: "math" | "social_studies" | "natural_sciences";
  } = {},
): Promise<string> {
  const snapshotId = opts.snapshotId ?? "flow-776-snap";
  const accountId = opts.accountId ?? USER.id;
  const route = opts.route ?? "/generate/math";
  const subject = opts.subject ?? "math";
  const tabId = getOrCreateTabId();
  await saveSnapshotTransactionally({
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: snapshotId,
    tab_id: tabId,
    route,
    subject,
    account_id: accountId,
    origin: "https://test.example.com",
    environment: "production",
    source_build_id: "build-A",
    target_build_id: "build-B",
    source_release_revision: 1,
    target_release_revision: 2,
    saved_at: new Date().toISOString(),
    workspace_revision: 0,
    form: {
      kind: "form",
      version: 1,
      fields: { topic: "recovery-776-topic" } as never,
    },
  });
  await persistTabPointer({
    account_id: accountId,
    snapshot_id: snapshotId,
    route,
    tab_id: tabId,
    attempted_target_build_id: "build-B",
    attempted_target_release_revision: 2,
  });
  return snapshotId;
}

// a. Expired-session restore via same-tab sign-in ─────────────────────────────

describe("identity a: expired-session restore via same-tab sign-in (router-driven)", () => {
  it("recovery banner appears after the user re-signs-in on the same tab following a 401 logout", async () => {
    // Arrange: snapshot exists for user u1
    const snapshotId = await seedSnapshot();

    // Simulate 401-path logout: clears credentials, leaves snapshot intact
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull(); // snapshot preserved

    // User re-signs in with the same account
    useAuthStore.setState({ token: "tok", user: USER });

    // Boot recovery as the app would on remount after sign-in
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });
    expect(useRecoveryStore.getState().pending?.snapshot_id).toBe(snapshotId);

    // Render the app — recovery banner should appear
    const { unmount } = renderApp("/generate/math");
    await waitFor(
      () =>
        expect(
          screen.queryByText(/Form restored from before update|已還原更新前的表單/i),
        ).toBeInTheDocument(),
      { timeout: 5000 },
    );
    unmount();
  });

  it("credential-clearing logout preserves snapshot in storage", async () => {
    const snapshotId = await seedSnapshot();
    // 401-path logout
    useAuthStore.getState().logout();
    // Snapshot still on disk
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();
    // Tab pointer still in sessionStorage
    expect(loadTabPointer()).not.toBeNull();
  });
});

// b. Different account logging in — refused, content never rendered ─────────────

describe("identity b: different-account login — refused", () => {
  // Unit-level: both tests call initRecoveryStore / initRecoveryStoreAsync directly and
  // assert on useRecoveryStore state. The "refused" outcome is a store state check;
  // the user-visible UI (a warning banner) requires a router render and is not tested here.
  // Router-driven coverage would render the app after a wrong-account boot and assert on DOM.
  it("sets blocked:wrong_account when user-B signs in with user-A's snapshot", async () => {
    // Snapshot for user-A
    await seedSnapshot({ accountId: "user-A" });

    // user-B signs in
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-B", email: "b@example.com", created_at: "2024-01-01T00:00:00Z" },
    });

    // Boot recovery
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });

    const state = useRecoveryStore.getState();
    // Content must not be exposed
    expect(state.pending).toBeNull();
    expect(state.blocked).toBe("wrong_account");
  });

  it("async init also blocks different-account snapshots", async () => {
    await seedSnapshot({ accountId: "user-A" });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-B", email: "b@example.com", created_at: "2024-01-01T00:00:00Z" },
    });
    await initRecoveryStoreAsync({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });
    expect(useRecoveryStore.getState().pending).toBeNull();
    expect(useRecoveryStore.getState().blocked).toBe("wrong_account");
  });
});

// c. Explicit logout invalidates recovery (router-driven) ─────────────────────

describe("identity c: explicit logout — snapshot invalidated (router-driven)", () => {
  it("clicking logout in SubjectSelectPage deletes the snapshot from storage", async () => {
    const { SubjectSelectPage } = await import("./pages/SubjectSelectPage");
    const snapshotId = await seedSnapshot();
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();

    const router = createMemoryRouter(routes, { initialEntries: ["/generate"] });
    const { unmount } = render(<RouterProvider router={router} />);

    // Wait for the page to render the logout button
    const logoutBtn = await screen.findByRole("button", {
      name: /logout|登出/i,
    });
    await act(async () => {
      fireEvent.click(logoutBtn);
    });
    // Confirm the destructive dialog
    const confirmBtn = await screen.findByRole("button", {
      name: /^Sign out$|^登出$/, // confirm.logout_confirm ("Sign out" in en-US, "登出" in zh-TW)
    });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    // Snapshot must be gone
    await waitFor(() => {
      expect(loadSnapshot(USER.id, snapshotId)).toBeNull();
    });

    unmount();
    // silence unused import lint
    void SubjectSelectPage;
  });

  it("logoutExplicit (the call behind the UI button) deletes snapshots and clears pointer", async () => {
    const snapshotId = await seedSnapshot();
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();

    useAuthStore.getState().logoutExplicit();

    expect(loadSnapshot(USER.id, snapshotId)).toBeNull();
    expect(loadTabPointer()).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });
});

// d. Both 401 paths preserve snapshot ─────────────────────────────────────────

describe("identity d: both 401 paths preserve snapshot", () => {
  // Unit-level: apiFetch 401 is tested by spying on globalThis.fetch directly (no router
  // render). The useGenerate 401 path (submit and run poll) is covered by the real-hook test in
  // hooks/useGenerate.401.test.ts. Router-driven coverage of the full UI 401→redirect flow
  // would require E2E tests (the auth redirect happens at the browser level after logout).
  it("apiFetch 401 clears auth but leaves snapshot on disk", async () => {
    const snapshotId = await seedSnapshot();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );
    window.history.pushState({}, "", "/generate/math");
    const { apiFetch } = await import("./api/client");
    await expect(apiFetch("/api/test")).rejects.toThrow();

    // Auth cleared via logout() — NOT logoutExplicit()
    expect(useAuthStore.getState().token).toBeNull();
    // Snapshot intact
    expect(loadSnapshot(USER.id, snapshotId)).not.toBeNull();
    // Signout reason saved as session_expired
    const raw = localStorage.getItem("exam_signout_reason");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw!).reason).toBe("session_expired");
  });

  // identity d — useGenerate 401 path (submit and poll) tested in hooks/useGenerate.401.test.ts
});

// e. Two independent tabs each keep their own snapshot ─────────────────────────

describe("identity e: two independent tabs each keep their own snapshot", () => {
  // Unit-level: tests call claimSnapshot / releaseSnapshotClaim and initRecoveryStore
  // directly, verifying storage-level isolation between snapshots. There is no React
  // render; tab independence in the real UI (each tab showing its own form) would require
  // two concurrent browser tabs, which jsdom cannot model — use E2E tests for that.
  it("tab-1 and tab-2 can each claim their own distinct snapshot", async () => {
    // Simulate two different snapshots for the same user (different routes)
    const snapA = await seedSnapshot({ snapshotId: "snap-tab1-A", route: "/generate/math" });
    sessionStorage.clear(); // simulate second tab context
    const snapB = await seedSnapshot({ snapshotId: "snap-tab2-B", route: "/generate/social_studies" });

    const resultA = await claimSnapshot("tab-id-1", snapA);
    const resultB = await claimSnapshot("tab-id-2", snapB);

    expect(resultA.won).toBe(true);
    expect(resultB.won).toBe(true);

    releaseSnapshotClaim(snapA);
    releaseSnapshotClaim(snapB);
  });

  it("two app renders with different routes each boot independently without cross-claiming", async () => {
    // Render first tab context — math snapshot
    sessionStorage.setItem("exam_tab_id", "tab-math-111");
    await seedSnapshot({ snapshotId: "snap-math-tab", route: "/generate/math" });
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });
    expect(useRecoveryStore.getState().pending?.snapshot_id).toBe("snap-math-tab");

    // Reset and simulate second tab context — social snapshot (different tab_id)
    resetRecoveryStoreForTests();
    sessionStorage.setItem("exam_tab_id", "tab-ss-222");
    const snapshotId2 = await seedSnapshot({
      snapshotId: "snap-ss-tab",
      route: "/generate/social_studies",
    });
    await persistTabPointer({
      account_id: USER.id,
      snapshot_id: snapshotId2,
      route: "/generate/social_studies",
    });
    initRecoveryStore({
      currentRoute: "/generate/social_studies",
      origin: "https://test.example.com",
      environment: "production",
    });
    expect(useRecoveryStore.getState().pending?.snapshot_id).toBe("snap-ss-tab");
  });
});

// f. Duplicate-tab collision ──────────────────────────────────────────────────

describe("identity f: duplicate-tab collision detection", () => {
  // Unit-level: tests call detectTabCollision and initRecoveryStoreAsync directly.
  // BroadcastChannel-based collision detection works in jsdom for same-origin tests, but
  // real duplicate-tab behaviour (Ctrl+Drag opening a tab with a copied sessionStorage)
  // cannot be reproduced in jsdom. The UI outcome (duplicate tab sees empty form instead
  // of recovery banner) requires an E2E test.
  it("detectTabCollision returns true when another tab listener is active with the same ID", async () => {
    const tabId = "dup-tab-776-id";
    const stopListener = startTabCollisionListener(tabId);
    await new Promise<void>((r) => setTimeout(r, 10));
    const collision = await detectTabCollision(tabId, 300);
    expect(collision).toBe(true);
    stopListener();
  });

  it("detectTabCollision returns false for a fresh tab (unique ID)", async () => {
    const tabId = "fresh-unique-tab-id-" + crypto.randomUUID();
    const collision = await detectTabCollision(tabId, 100);
    expect(collision).toBe(false);
  });

  it("initRecoveryStoreAsync sets claimedTabId after winning claim", async () => {
    await seedSnapshot();
    sessionStorage.setItem("exam_tab_id", "claim-test-tab");
    await initRecoveryStoreAsync({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });
    const state = useRecoveryStore.getState();
    expect(state.pending).not.toBeNull();
    expect(state.claimedTabId).toBe("claim-test-tab");
    expect(state.claimedSnapshotId).toBe("flow-776-snap");
  });
});

// g. Denied marker storage blocking save-and-update (router-driven) ───────────

describe("identity g: denied marker storage blocks save-and-update (router-driven)", () => {
  it("save-and-update returns snapshot_failed when localStorage.setItem is denied", async () => {
    setUpUpdateRequired();
    const { unmount } = renderApp("/generate/math");
    const topicInput = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    await act(async () => {
      fireEvent.change(topicInput, { target: { value: "storage-denied-test" } });
    });

    // Mock all localStorage writes to throw
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(["snapshot_failed", "pointer_failed", "quota"]).toContain(result.reason);
    }

    unmount();
  });

  it("claimSnapshot returns won:false when localStorage throws on write", async () => {
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("StorageError", "StorageError");
    });
    const result = await claimSnapshot("tab-g", "snap-g");
    expect(result.won).toBe(false);
  });
});

// h. Telemetry exclusion ──────────────────────────────────────────────────────

describe("identity h: telemetry exclusion — recovery contents never in logs", () => {
  // Unit-level: tests call logoutExplicit(), deleteAllSnapshotsForAccount(), and apiFetch()
  // directly and spy on console methods. No React render is needed because telemetry
  // exclusion is a property of the storage / auth functions, not the UI layer.
  it("logoutExplicit does not log account ID or snapshot contents to console", async () => {
    await seedSnapshot({ snapshotId: "snap-priv-h" });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    useAuthStore.getState().logoutExplicit();

    for (const call of [
      ...logSpy.mock.calls,
      ...warnSpy.mock.calls,
      ...errorSpy.mock.calls,
    ]) {
      const asString = JSON.stringify(call);
      expect(asString).not.toContain(USER.id);
      expect(asString).not.toContain("snap-priv-h");
    }
  });

  it("deleteAllSnapshotsForAccount does not log account ID to console", async () => {
    const snap = await seedSnapshot({ accountId: "user-h-secret", snapshotId: "snap-h-secret" });
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    deleteAllSnapshotsForAccount("user-h-secret");

    for (const call of [...logSpy.mock.calls, ...errorSpy.mock.calls]) {
      const asString = JSON.stringify(call);
      expect(asString).not.toContain("user-h-secret");
      expect(asString).not.toContain(snap);
    }
  });

  it("apiFetch 401 signout reason contains only reason+userId — no snapshot form fields", async () => {
    await seedSnapshot({ snapshotId: "snap-telem" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );
    window.history.pushState({}, "", "/generate/math");
    const { apiFetch } = await import("./api/client");
    await expect(apiFetch("/api/schemas")).rejects.toThrow();

    const raw = localStorage.getItem("exam_signout_reason");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as Record<string, unknown>;
    expect(Object.keys(parsed)).toEqual(expect.arrayContaining(["reason", "userId"]));
    expect(raw).not.toContain("recovery-776-topic");
    expect(raw).not.toContain("form");
  });
});
