/**
 * ParamForm 確認頁修改 preview re-fetch tests (ticket #445)
 *
 * 全域池 / 預抽 / 釘選 / 確認頁修改 / 重抽 vocabulary — see CONTEXT.md.
 *
 * These tests are isolated from ParamForm.confirmation-display.test.tsx so that
 * vi.useFakeTimers() is contained and does not interfere with other suites.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// --- mock setup (idiom from ParamForm.confirmation-display.test.tsx) ---
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

// --- schema fixtures (same shapes as confirmation-display.test.tsx) ---
const MATH_SCHEMA = {
  學習階段: "第四學習階段", grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }], 題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }], 數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }], 題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }], 學習表現: [], 學習內容: [],
};

const SOCIAL_SCHEMA = {
  ...MATH_SCHEMA,
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
};

// --- deferred promise helper ---
function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

// Open the confirmation screen for a social_studies form that has 3 subquestion cards.
// Passes core_question so coreQuestionResolution stays "idle" and the initial preview
// fetch proceeds without needing planCoreQuestions to resolve.
async function openConfirmationWithSubquestions() {
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={vi.fn()}
      disabled={false}
      initialParams={{
        sub_question_count: 3,
        subquestion_configs: [{}, {}, {}],
        core_question: "測試核心問題",
        topic: "台灣歷史",
      }}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  await screen.findByRole("heading", { name: "發送前確認設定" });
  // Wait for the one-shot initial preview fetch to complete.
  await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
}

describe("ParamForm 確認頁修改 preview re-fetch (#445)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: ["候選核心問題"] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── Slice 1 ────────────────────────────────────────────────────────────────
  // Criterion: an edit on a 題組's card re-fetches that 題組's previews with
  // the edited values.
  it("slice 1 — 確認頁修改 re-fetches previews; second call carries the edited values", async () => {
    await openConfirmationWithSubquestions();

    // Edit the first 題組's first subquestion instruction (確認頁修改).
    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");
    fireEvent.change(firstInstructionTextarea, { target: { value: "新出題指示" } });

    // Advance past the ~500 ms debounce.
    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // The second call must encode the edited subquestion config.
    const secondCallParams = previewGenerateMock.mock.calls[1][0];
    const perQuestion = JSON.parse(secondCallParams.per_question_params as string) as Array<{
      subquestion_configs: string;
    }>;
    const firstQuestionSubqConfigs = JSON.parse(perQuestion[0].subquestion_configs) as Array<{
      instruction?: string;
    }>;
    expect(firstQuestionSubqConfigs[0].instruction).toBe("新出題指示");
  });

  // ── Slice 2 ────────────────────────────────────────────────────────────────
  // Criterion: rapid successive edits within the debounce window produce a
  // single request (count assertion, not a timing vibe).
  it("slice 2 — rapid 確認頁修改 within the debounce window produce exactly one re-fetch", async () => {
    await openConfirmationWithSubquestions();
    const callsAfterInitial = previewGenerateMock.mock.calls.length; // = 1

    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");

    // Three rapid edits, each 200 ms apart — all within the 500 ms debounce window.
    fireEvent.change(firstInstructionTextarea, { target: { value: "指示A" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    fireEvent.change(firstInstructionTextarea, { target: { value: "指示B" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    fireEvent.change(firstInstructionTextarea, { target: { value: "指示C" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    // Debounce has not fired yet — no additional call.
    expect(previewGenerateMock).toHaveBeenCalledTimes(callsAfterInitial);

    // Advance the remaining time so the debounce fires (500 ms from last edit; 300 ms remain).
    await act(async () => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(callsAfterInitial + 1));

    // Exactly one extra call — the three edits were coalesced into one request.
    expect(previewGenerateMock).toHaveBeenCalledTimes(callsAfterInitial + 1);
  });

  // ── Slice 3 ────────────────────────────────────────────────────────────────
  // Criterion: a loading indicator shows while the re-fetch is in flight.
  it("slice 3 — loading indicator is visible during the in-flight re-fetch", async () => {
    const { promise: fetchPromise, resolve: fetchResolve } = deferred<{ prompts: never[] }>();
    // Initial fetch resolves immediately (from beforeEach default).
    // Subsequent fetch is slow (deferred).
    previewGenerateMock.mockResolvedValueOnce({ prompts: [] });
    previewGenerateMock.mockReturnValueOnce(fetchPromise);

    await openConfirmationWithSubquestions();

    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");
    fireEvent.change(firstInstructionTextarea, { target: { value: "指示" } });

    // Fire the debounce.
    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // Loading indicator must be visible while the fetch is still pending.
    expect(screen.getByText("提示詞預覽載入中…")).toBeInTheDocument();

    // Resolve the slow fetch.
    await act(async () => { fetchResolve({ prompts: [] }); });

    // Loading indicator must disappear once the fetch completes.
    await waitFor(() => expect(screen.queryByText("提示詞預覽載入中…")).not.toBeInTheDocument());
  });

  // ── Slice 4 ────────────────────────────────────────────────────────────────
  // Criterion: after the re-fetch, previews reflect the edited configuration.
  it("slice 4 — previews are updated to reflect the edited configuration after re-fetch", async () => {
    const updatedSystemPrompt = "新系統提示詞";
    const updatedUserPrompt = "新使用者提示詞";

    previewGenerateMock.mockResolvedValueOnce({ prompts: [] }); // initial fetch — no previews
    previewGenerateMock.mockResolvedValueOnce({                  // re-fetch — returns new preview
      prompts: [
        {
          index: 0,
          subquestion_index: undefined,
          system_prompt: updatedSystemPrompt,
          user_prompt: updatedUserPrompt,
        },
      ],
    });

    await openConfirmationWithSubquestions();

    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");
    fireEvent.change(firstInstructionTextarea, { target: { value: "新指示" } });

    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // The updated prompt content must now be rendered in the DOM.
    // (<details> children are always in jsdom DOM regardless of open state.)
    await waitFor(() => expect(screen.getByText(updatedSystemPrompt)).toBeInTheDocument());
    expect(screen.getByText(updatedUserPrompt)).toBeInTheDocument();
  });
});
