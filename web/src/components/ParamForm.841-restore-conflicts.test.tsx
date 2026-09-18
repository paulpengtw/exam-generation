/**
 * Issue #841: restored drafts and history/Regenerate prefills keep and flag
 * 科目/內容領域 conflicts.
 *
 * A draft, history record, or Regenerate prefill can restore a 科目 or
 * 內容領域 that conflicts with its 釘選 codes (earlier versions of the form
 * allowed it). This must never be silently fixed: both the parent value and
 * the conflicting code(s) are kept, the conflicting parent control is marked
 * `aria-invalid` with the Task 8 narrowing hint, and `產生` stays disabled
 * until the teacher changes the parent or deselects the code(s). Absence is
 * judged against the grade's *whole* curriculum pool (schemas.學習內容 /
 * 學習表現), not the 科目/內容領域-filtered `available*` lists — only a code
 * truly absent from the grade is deselected and reported via the existing
 * history/Regenerate dropped-codes notice; draft restore has no such notice
 * and none is added.
 *
 * History prefill and Regenerate prefill are mechanistically the same code
 * path from ParamForm's point of view: `HistoryDetail`'s "Regenerate" button
 * (src/pages/HistoryDetail.tsx) navigates with
 * `state: { prefillParams: detail.params_json }`, which GeneratePage forwards
 * to ParamForm as the same `initialParams` prop a plain history prefill uses.
 * There is no separate "regenerate" branch inside ParamForm to exercise
 * differently, so one shared helper covers both acceptance bullets.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FormFields } from "./ParamForm";
import type {
  ConfirmationWorkspaceSnapshot,
  FormWorkspaceSnapshot,
} from "../lib/workspace/adapters/types";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const DOMAIN_ADMITTED = "Civic Institutions and Systems";
const DOMAIN_CONFLICT = "Civic Participation";
// From the ticket text verbatim.
const LC_DRAFT_CIVIC = "公Bn-Ⅳ-3"; // admits DOMAIN_ADMITTED only, not DOMAIN_CONFLICT
const LC_HISTORY_CIVIC = "公Bj-Ⅳ-1"; // admits 公民與社會/跨科 only, not 地理/歷史
const LC_HIST = "歷Ka-Ⅳ-1"; // admits 歷史/跨科 only
const LC_GEO = "地Aa-Ⅳ-1"; // admits 地理/跨科 only
const LC_ABSENT = "歷Zz-Ⅳ-9"; // never appears in the schema below — grade-absent

const SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [
    { value: "歷史", instruction: "" },
    { value: "地理", instruction: "" },
    { value: "公民與社會", instruction: "" },
    { value: "跨科", instruction: "" },
  ],
  內容領域: [
    { value: DOMAIN_ADMITTED, instruction: "" },
    { value: DOMAIN_CONFLICT, instruction: "" },
  ],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    {
      value: "社1a-Ⅳ-1",
      instruction: "",
      科目: "社",
      admitted_by: { 科目: ["歷史", "地理", "公民與社會", "跨科"] },
    },
  ],
  學習內容: [
    {
      value: LC_DRAFT_CIVIC,
      instruction: "",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN_ADMITTED] },
    },
    {
      value: LC_HISTORY_CIVIC,
      instruction: "",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"] },
    },
    {
      value: LC_HIST,
      instruction: "",
      科目: "歷",
      admitted_by: { 科目: ["歷史", "跨科"] },
    },
    {
      value: LC_GEO,
      instruction: "",
      科目: "地",
      admitted_by: { 科目: ["地理", "跨科"] },
    },
  ],
  digital_only_question_types: [],
};

function mockCollaborators() {
  getSchemasMock.mockResolvedValue(SCHEMA);
  getAvailableModelsMock.mockResolvedValue({
    allowed: [],
    defaults: { plan: "", execute: "", verify: "", correct: "" },
  });
  planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
  previewGenerateMock.mockResolvedValue({ prompts: [] });
  resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
    payload,
    drawn: [],
    cleared: [],
  }));
}

async function renderWithInitialParams(initialParams: Record<string, unknown>) {
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={vi.fn()}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  await screen.findByRole("button", { name: "產生" });
}

function subjectSelect() {
  return screen.getByRole("combobox", { name: "科目" }) as HTMLSelectElement;
}

function domainSelect() {
  return screen.getByRole("combobox", { name: "內容領域" }) as HTMLSelectElement;
}

function generateButton() {
  return screen.getByRole("button", { name: "產生" });
}

// The multi-select `<select multiple>` in ConfirmationMultiSelect is React
// controlled; simulating a real single-item click via `userEvent.selectOptions`
// leaves stale native selection state (a known interaction quirk with
// controlled multi-selects), so this sets the DOM selection directly and
// fires one native `change`, exactly as `ConfirmationMultiSelect`'s onChange
// reads it (`event.currentTarget.selectedOptions`).
function selectExactly(select: HTMLSelectElement, values: readonly string[]): void {
  for (const option of Array.from(select.options)) {
    option.selected = values.includes(option.value);
  }
  fireEvent.change(select);
}

function draftKey(userId: string): string {
  return `exam_form_draft_${userId}`;
}

function signIn(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-841",
    email: "teacher-841@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

const DRAFT_FIELDS: FormFields = {
  grade: 7,
  style: "",
  contentType: "純文字",
  customContentType: "",
  context: ["個人"],
  setType: "題組題",
  qType: ["選擇題"],
  count: 1,
  coverageMode: "balanced",
  skipVerify: false,
  disableReferenceFewshot: false,
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image",
  difficulty: "",
  reportingScale: "",
  subjectFilter: "",
  passage: "保存的文本",
  textWordLimit: null,
  textInstruction: "",
  options: [],
  topic: "保存的主題",
  coreQuestion: null,
  subContext: "",
  scienceCompetency: [],
  learningPerformance: [],
  learningContent: [LC_DRAFT_CIVIC],
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
  contentDomain: DOMAIN_CONFLICT,
  targetSurface: "紙本",
  allowDuplicateFigureKinds: false,
};

describe("#841 restored drafts and history/Regenerate prefills keep and flag 科目/內容領域 conflicts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    mockCollaborators();
  });

  it("draft restore: 內容領域 Civic Participation + 公Bn-Ⅳ-3 keeps both, marks 內容領域 invalid, and disables 產生", async () => {
    signIn();
    localStorage.setItem(
      draftKey("teacher-841"),
      JSON.stringify({ savedAt: new Date().toISOString(), fields: DRAFT_FIELDS }),
    );

    render(<ParamForm subject="social_studies" onSubmit={vi.fn()} disabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "還原草稿" }));

    // Both restored values are kept — never silently fixed.
    expect(await screen.findByText(LC_DRAFT_CIVIC)).toBeInTheDocument();
    await waitFor(() => expect(domainSelect().value).toBe(DOMAIN_CONFLICT));

    // 內容領域 is marked invalid with the Task 8 hint naming the constraining code.
    await waitFor(() => expect(domainSelect()).toHaveAttribute("aria-invalid", "true"));
    const hintId = domainSelect().getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId ?? "")?.textContent).toContain(LC_DRAFT_CIVIC);

    // 產生 stays disabled until the conflict is resolved.
    expect(generateButton()).toBeDisabled();

    // Draft restore has no dropped-codes notice — none is added by #841.
    expect(screen.queryByText(/已取消選取/)).not.toBeInTheDocument();
  });

  it("history prefill: 科目 地理 + 公Bj-Ⅳ-1 keeps the code, marks 科目 invalid, omits it from the dropped notice, and disables 產生; fixing 科目 clears it", async () => {
    await renderWithInitialParams({
      grade: 7,
      subject_filter: "地理",
      learning_content: [LC_HISTORY_CIVIC],
    });

    expect(await screen.findByText(LC_HISTORY_CIVIC)).toBeInTheDocument();
    expect(subjectSelect().value).toBe("地理");

    await waitFor(() => expect(subjectSelect()).toHaveAttribute("aria-invalid", "true"));
    const hintId = subjectSelect().getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId ?? "")?.textContent).toContain(LC_HISTORY_CIVIC);

    // Not reported as dropped — it is kept, only flagged as a conflict.
    expect(screen.queryByText(/已取消選取/)).not.toBeInTheDocument();

    expect(generateButton()).toBeDisabled();

    // Changing 科目 to an admitting value clears the invalid state and re-enables 產生.
    // (The narrowing hint itself is Task 8's general "these codes narrow the
    // option set" indicator and stays visible regardless of the current
    // selection — only `aria-invalid` and `產生` track the live conflict.)
    fireEvent.change(subjectSelect(), { target: { value: "公民與社會" } });
    await waitFor(() => expect(subjectSelect()).not.toHaveAttribute("aria-invalid", "true"));
    expect(generateButton()).not.toBeDisabled();
    // The code is still selected — 科目 was never silently changed to fix it for us.
    expect(screen.getByText(LC_HISTORY_CIVIC)).toBeInTheDocument();
  });

  it("Regenerate prefill (same initialParams path as a history prefill) behaves identically", async () => {
    await renderWithInitialParams({
      grade: 7,
      seed: 4242,
      subject_filter: "地理",
      learning_content: [LC_HISTORY_CIVIC],
    });

    expect(await screen.findByText(LC_HISTORY_CIVIC)).toBeInTheDocument();
    await waitFor(() => expect(subjectSelect()).toHaveAttribute("aria-invalid", "true"));
    expect(generateButton()).toBeDisabled();
    expect(screen.queryByText(/已取消選取/)).not.toBeInTheDocument();
  });

  it("a code absent from the grade's whole pool is still deselected and reported, alongside a kept 科目 conflict", async () => {
    await renderWithInitialParams({
      grade: 7,
      subject_filter: "地理",
      learning_content: [LC_HISTORY_CIVIC, LC_ABSENT],
    });

    // LC_ABSENT is truly absent from this grade's whole 學習內容 pool.
    await waitFor(() => expect(screen.queryByText(LC_ABSENT)).not.toBeInTheDocument());
    const notice = await screen.findByText(/已取消選取/);
    expect(notice.textContent).toContain(LC_ABSENT);
    // The 科目-conflicting (but grade-present) code is kept and stays out of this notice.
    expect(notice.textContent).not.toContain(LC_HISTORY_CIVIC);
    expect(screen.getByText(LC_HISTORY_CIVIC)).toBeInTheDocument();

    expect(subjectSelect()).toHaveAttribute("aria-invalid", "true");
    expect(generateButton()).toBeDisabled();
  });

  it("發送前確認: editing a 題組's 科目 to 地理 shows 地理-admitted 學習內容 codes", async () => {
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "social_studies",
        grade: 7,
        count: 1,
        per_question_params: JSON.stringify([
          {
            subject_filter: ["歷史"],
            sub_question_count: 1,
            subquestion_configs: JSON.stringify([{ question_type: "選擇題" }]),
          },
        ]),
      },
      drawn: ["per_question_params[0].科目"],
      cleared: [],
    });

    await renderWithInitialParams({ subject_filter: "歷史" });
    fireEvent.click(generateButton());
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const card = within(
      within(question.getByRole("heading", { name: "各小題配置", level: 4 }).closest("section") as HTMLElement)
        .getAllByRole("listitem")[0],
    );
    const lcInput = card.getByLabelText("學習內容");

    fireEvent.change(lcInput, { target: { value: "地" } });
    expect(card.queryByText(LC_GEO)).not.toBeInTheDocument();
    fireEvent.change(lcInput, { target: { value: "歷" } });
    expect(await card.findByText(LC_HIST)).toBeInTheDocument();

    const subjectDt = question.getByText("科目", { selector: "dt" });
    fireEvent.click(within(subjectDt.parentElement as HTMLElement).getByRole("button", { name: "編輯" }));
    const subjectListbox = screen.getByRole("listbox", { name: "科目" }) as HTMLSelectElement;
    selectExactly(subjectListbox, ["地理"]);

    fireEvent.change(lcInput, { target: { value: "歷" } });
    expect(card.queryByText(LC_HIST)).not.toBeInTheDocument();
    fireEvent.change(lcInput, { target: { value: "地" } });
    expect(await card.findByText(LC_GEO)).toBeInTheDocument();
  });
});

/**
 * Semantic interaction test: #773 recovered confirmation × #843 narrowing
 *
 * A confirmation saved under the old schema (before #843 admission rules) may
 * carry LC codes that are now incompatible with the stored subject_filter. On
 * recovery the confirmation must stay visible AND the 確定發送 button must be
 * blocked (confirmationInvalidFields catches the mismatched LC) — the codes
 * must NOT be silently dropped or rewritten.
 */
describe("#773 + #843 — recovered confirmation with narrowing-conflicting LC codes is visible but blocked", () => {
  const confirmedSubjectFilter = "地理"; // only 地Aa-Ⅳ-1 is admitted for 地理
  const conflictingLC = LC_HIST; // 歷Ka-Ⅳ-1 admits 歷史/跨科 only — conflicts with 地理

  function makeRecoveredForm(): FormWorkspaceSnapshot {
    return {
      kind: "form",
      version: 1,
      fields: {
        grade: 7,
        style: "",
        contentType: "純文字",
        customContentType: "",
        context: [],
        setType: "題組題",
        qType: ["選擇題"],
        count: 1,
        coverageMode: "balanced",
        skipVerify: false,
        disableReferenceFewshot: false,
        coreQuestionCallback: true,
        imageGenerationMode: "gpt_image",
        difficulty: "",
        reportingScale: "",
        subjectFilter: confirmedSubjectFilter,
        passage: "",
        textWordLimit: null,
        textInstruction: "",
        options: ["", "", "", ""],
        topic: "",
        coreQuestion: null,
        subContext: "",
        scienceCompetency: [],
        learningPerformance: [],
        learningContent: [conflictingLC],
        subQuestionCount: 1,
        subquestionConfigs: [{}],
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
  }

  function makeRecoveredConfirmation(): ConfirmationWorkspaceSnapshot {
    const row = {
      subject: "social_studies",
      grade: 7,
      count: 1,
      subject_filter: confirmedSubjectFilter,
      learning_content: [conflictingLC],
      sub_question_count: 1,
      subquestion_configs: JSON.stringify([
        { question_type: "選擇題", learning_content: [conflictingLC] },
      ]),
      seed: 42,
    };
    return {
      kind: "confirmation",
      version: 1,
      pendingParams: row as Record<string, unknown>,
      pendingPerQuestionParams: [row as Record<string, unknown>],
      clearedPaths: [],
      hasPendingConfirmationEdits: false,
      redraws: {},
      historyDraftChoice: null,
      pendingPrefill: null,
      coreQuestionResolution: "idle",
    };
  }

  beforeEach(() => {
    mockCollaborators();
  });

  it("shows the confirmation section with the conflicting code visible, 確定發送 disabled", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        recoveredForm={makeRecoveredForm()}
        recoveredConfirmation={makeRecoveredConfirmation()}
      />,
    );

    // The confirmation section is mounted from the recovered snapshot.
    // Wait for schemas to load so confirmationInvalidFields can be computed.
    await screen.findByRole("heading", { name: "發送前確認設定" });

    // The conflicting LC code must be visible — not silently removed (may
    // appear multiple times: top-level and per-subquestion rows).
    const codeElements = screen.getAllByText(conflictingLC);
    expect(codeElements.length).toBeGreaterThan(0);

    // The 確定發送 button must be disabled because the LC code is incompatible
    // with the stored subject_filter under the current #843 admission rules.
    // confirmationInvalidFields detects this and sets confirmationHasInvalidFields=true.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "確定發送" }),
      ).toBeDisabled();
    });
  });
});
