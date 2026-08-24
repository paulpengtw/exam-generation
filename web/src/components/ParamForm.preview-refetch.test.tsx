/**
 * ParamForm 確認頁修改 preview re-fetch tests (ticket #445)
 *
 * 全域池 / 預抽 / 釘選 / 確認頁修改 / 重抽 vocabulary — see CONTEXT.md.
 *
 * These tests are isolated from ParamForm.confirmation-display.test.tsx so that
 * vi.useFakeTimers() is contained and does not interfere with other suites.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  // ── Regression: no spurious re-fetch on confirmation open (#445) ──────────
  // Opening the confirmation screen must not trigger a second previewGenerate
  // call even after the debounce window elapses.
  it("regression — opening confirmation with zero 確認頁修改 issues exactly one preview request", async () => {
    await openConfirmationWithSubquestions();

    // Advance well past the 500 ms debounce; if the debounce was gated only on
    // pendingPerQuestionParams (set on confirmation open) this would fire a second call.
    await act(async () => { vi.advanceTimersByTime(1000); });
    // Flush any pending microtasks / promise resolutions.
    await act(async () => { await Promise.resolve(); });

    expect(previewGenerateMock).toHaveBeenCalledTimes(1);
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
    // After the initial fetch the call count must be exactly 1 (regression guard:
    // no spurious re-fetch on confirmation open).
    expect(previewGenerateMock).toHaveBeenCalledTimes(1);

    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");

    // Three rapid edits, each 200 ms apart — all within the 500 ms debounce window.
    fireEvent.change(firstInstructionTextarea, { target: { value: "指示A" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    fireEvent.change(firstInstructionTextarea, { target: { value: "指示B" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    fireEvent.change(firstInstructionTextarea, { target: { value: "指示C" } });
    await act(async () => { vi.advanceTimersByTime(200); });

    // Debounce has not fired yet — no additional call.
    expect(previewGenerateMock).toHaveBeenCalledTimes(1);

    // Advance the remaining time so the debounce fires (500 ms from last edit; 300 ms remain).
    await act(async () => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // Exactly one extra call — the three edits were coalesced into one request.
    expect(previewGenerateMock).toHaveBeenCalledTimes(2);
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

// ── #446 — Stale badge + retry after fetch failure ─────────────────────────
describe("ParamForm 確認頁修改 preview fetch-failure stale badge + retry (#446)", () => {
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

  // ── Slice 5 (criterion 1) ─────────────────────────────────────────────────
  // A failed preview re-fetch shows a stale badge on the affected 題組.
  it("slice 5 — failed re-fetch shows stale badge on the affected 題組", async () => {
    previewGenerateMock.mockResolvedValueOnce({ prompts: [] }); // initial fetch succeeds
    previewGenerateMock.mockRejectedValueOnce(new Error("Network error")); // re-fetch fails

    await openConfirmationWithSubquestions();
    expect(previewGenerateMock).toHaveBeenCalledTimes(1);

    // 確認頁修改: edit the first subquestion's instruction
    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");
    fireEvent.change(firstInstructionTextarea, { target: { value: "新出題指示" } });

    // Advance past the debounce window
    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // After the failed re-fetch, the stale badge must be visible
    await waitFor(() => expect(screen.getByText("預覽已過期")).toBeInTheDocument());
    // And a retry button must be present with accessible label
    expect(screen.getByRole("button", { name: "重新載入預覽" })).toBeInTheDocument();
  });

  // ── Slice 6 (criterion 2) ─────────────────────────────────────────────────
  // Retry re-runs the fetch; on success the badge clears and previews update.
  // A failed retry keeps the badge and allows retrying again.
  it("slice 6 — retry clears the stale badge on success; failed retry preserves it", async () => {
    const updatedSystemPrompt = "重試後系統提示詞";

    previewGenerateMock.mockResolvedValueOnce({ prompts: [] }); // initial fetch
    previewGenerateMock.mockRejectedValueOnce(new Error("Network error")); // re-fetch fails
    previewGenerateMock.mockRejectedValueOnce(new Error("Still failing")); // first retry fails
    previewGenerateMock.mockResolvedValueOnce({                            // second retry succeeds
      prompts: [
        {
          index: 0,
          subquestion_index: undefined,
          system_prompt: updatedSystemPrompt,
          user_prompt: "重試後使用者提示詞",
        },
      ],
    });

    await openConfirmationWithSubquestions();

    // 確認頁修改 to trigger re-fetch
    const [firstInstructionTextarea] = screen.getAllByLabelText("出題指示");
    fireEvent.change(firstInstructionTextarea, { target: { value: "觸發重新取得" } });
    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // Stale badge should appear after the re-fetch failure
    await waitFor(() => expect(screen.getByText("預覽已過期")).toBeInTheDocument());
    const retryButton = screen.getByRole("button", { name: "重新載入預覽" });

    // First retry fails — badge must remain, retry button must still be present
    fireEvent.click(retryButton);
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getByText("預覽已過期")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "重新載入預覽" })).toBeInTheDocument();

    // Second retry succeeds — badge must disappear, updated preview must appear
    fireEvent.click(screen.getByRole("button", { name: "重新載入預覽" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(screen.queryByText("預覽已過期")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(updatedSystemPrompt)).toBeInTheDocument());
  });

  // ── Slice 7 (criterion 3) ─────────────────────────────────────────────────
  // Other 題組's previews are unaffected by one 題組's fetch failure.
  // Uses count=2 so the confirmation screen shows two 題組 sections.
  it("slice 7 — stale badge appears only on the edited 題組, not on other 題組s", async () => {
    previewGenerateMock.mockResolvedValueOnce({ prompts: [] }); // initial fetch
    previewGenerateMock.mockRejectedValueOnce(new Error("Network error")); // re-fetch fails

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          count: 2,
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
          core_question: "測試核心問題",
          topic: "台灣歷史",
        }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));

    // Edit 題組 0's first subquestion instruction (確認頁修改).
    // With count=2 and sub_question_count=3, textareas[0] belongs to 題組 0.
    const allInstructionTextareas = screen.getAllByLabelText("出題指示");
    fireEvent.change(allInstructionTextareas[0], { target: { value: "第一題組的新指示" } });

    await act(async () => { vi.advanceTimersByTime(500); });
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    // 題組 0 (第1題) must show the stale badge
    const group1Section = screen.getByRole("region", { name: "第1題" });
    await waitFor(() =>
      expect(within(group1Section).getByText("預覽已過期")).toBeInTheDocument(),
    );

    // 題組 1 (第2題) must NOT show the stale badge — it was not edited
    const group2Section = screen.getByRole("region", { name: "第2題" });
    expect(within(group2Section).queryByText("預覽已過期")).not.toBeInTheDocument();
  });
});
