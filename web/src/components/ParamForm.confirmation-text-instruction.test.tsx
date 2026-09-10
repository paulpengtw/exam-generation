/**
 * Tests for per-題組 文本出題指示 確認頁修改 (issue #637).
 *
 * Acceptance criteria covered:
 *  1. Each 題組 is prefilled with the request-level text_instruction.
 *  2. Editing one 題組's textarea leaves its sibling unchanged.
 *  3. Clearing an edited field reverts that 題組 to the request-level value.
 *  4. The submitted payload carries the per-行 override only in the edited 題組 row.
 *  5. 提示詞預覽 is refetched after an edit, reflecting the changed value.
 *  6. Parity: the same behaviour applies for natural_sciences.
 *  7. Editing one 題組's confirmation field does NOT change the submitted
 *     request-level text_instruction (the form's own value is isolated).
 *  8. After returning from confirmation, the form's 文本出題指示 input still
 *     shows the original value, and the localStorage draft is uncontaminated.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() =>
  vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } }))
);
const planCoreQuestionsMock = vi.hoisted(() =>
  vi.fn(async () => ({ candidates: [] }))
);
const previewGenerateMock = vi.hoisted(() => vi.fn(async () => ({ prompts: [] })));
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import { useAuthStore } from "../store/authStore";
import ParamForm from "./ParamForm";

// ── Draft-persistence helpers (parallel to ParamForm.draft-persistence.test.tsx) ─
const DRAFT_KEY = "exam_form_draft_teacher-1";

function signInAsTeacher(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-1",
    email: "teacher@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

// ── Shared schema fixtures ────────────────────────────────────────────────────

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const SCIENCE_SCHEMA = {
  ...SOCIAL_SCHEMA,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
};

// ── Resolver stub ─────────────────────────────────────────────────────────────

/**
 * A minimal confirm-screen resolver that echoes back the rows with a
 * generated seed, mirroring what the production resolver does for seeded batches.
 */
function makeResolveStub(subject = "social_studies") {
  return async (payload: Record<string, unknown>) => {
    const rawRows = payload.per_question_params;
    const sourceRows: Record<string, unknown>[] =
      typeof rawRows === "string"
        ? (JSON.parse(rawRows) as Record<string, unknown>[])
        : Array.isArray(rawRows)
          ? (rawRows as Record<string, unknown>[])
          : [];

    // Exclude request-level-only fields that the real resolver does not
    // propagate into individual per-question rows (mirrors _BATCH_REQUEST_LEVEL_FIELDS).
    // text_instruction in particular must NOT be spread into rows — the server
    // falls back to params.text_instruction when no per-row override is present.
    const REQUEST_LEVEL_ONLY = new Set([
      "subject", "count", "per_question_params", "drawn", "redraws",
      "text_instruction",
    ]);
    const base = Object.fromEntries(
      Object.entries(payload).filter(([k]) => !REQUEST_LEVEL_ONLY.has(k)),
    );
    const generatedSeed = typeof payload.seed !== "number";
    const seed = generatedSeed ? 900 : (payload.seed as number);

    const resolvedRows = sourceRows.map((sourceRow, index) => {
      const row: Record<string, unknown> = { ...base, ...sourceRow };
      delete row.subject;
      delete row.count;
      delete row.per_question_params;
      delete row.drawn;
      delete row.redraws;
      if (sourceRow.seed === undefined || sourceRow.seed === null) row.seed = seed + index;
      if (
        row.context === undefined ||
        (Array.isArray(row.context) && (row.context as unknown[]).length === 0)
      ) {
        row.context = [subject === "natural_sciences" ? "Personal" : "個人"];
      }
      return row;
    });

    return {
      payload: {
        ...payload,
        ...(generatedSeed ? { seed } : {}),
        per_question_params: JSON.stringify(resolvedRows),
      },
      drawn: generatedSeed ? ["seed"] : ([] as string[]),
    };
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function openConfirmation(
  subject: "social_studies" | "natural_sciences",
  initialParams: Record<string, unknown> = {},
  onSubmit = vi.fn(),
) {
  render(
    <ParamForm subject={subject} onSubmit={onSubmit} disabled={false} initialParams={initialParams} />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  return screen.findByRole("heading", { name: "發送前確認設定" });
}

/** Return the text_instruction textarea inside the given 題組 region. */
function textInstructionTextarea(questionRegion: ReturnType<typeof within>) {
  return questionRegion.getByLabelText("文本出題指示") as HTMLTextAreaElement;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ParamForm 確認頁修改 per-題組 文本出題指示 (#637)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(makeResolveStub("social_studies"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── 1. Prefill ──────────────────────────────────────────────────────────────

  it("prefills each 題組 textarea with the request-level text_instruction", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      count: 2,
      text_instruction: "請聚焦在資料判讀",
    });

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q2 = within(screen.getByRole("region", { name: "第2題" }));

    expect(textInstructionTextarea(q1).value).toBe("請聚焦在資料判讀");
    expect(textInstructionTextarea(q2).value).toBe("請聚焦在資料判讀");
  });

  // ── 2. Isolation — editing one leaves siblings untouched ────────────────────

  it("editing 題組 1 does not affect 題組 2's textarea", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      count: 2,
      text_instruction: "原始指示",
    });

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q2 = within(screen.getByRole("region", { name: "第2題" }));
    const q1ta = textInstructionTextarea(q1);
    const q2ta = textInstructionTextarea(q2);

    await act(async () => {
      fireEvent.change(q1ta, { target: { value: "第一題組覆寫" } });
    });

    expect(q1ta.value).toBe("第一題組覆寫");
    expect(q2ta.value).toBe("原始指示");
  });

  // ── 3. Clearing reverts to request-level value ──────────────────────────────

  it("clearing an edited value reverts that 題組 to the request-level text_instruction", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      count: 2,
      text_instruction: "請聚焦在原因分析",
    });

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q1ta = textInstructionTextarea(q1);

    // Edit then clear
    await act(async () => {
      fireEvent.change(q1ta, { target: { value: "暫時覆寫" } });
    });
    expect(q1ta.value).toBe("暫時覆寫");

    await act(async () => {
      fireEvent.change(q1ta, { target: { value: "" } });
    });
    // After clearing, should fall back to the request-level value
    expect(q1ta.value).toBe("請聚焦在原因分析");
  });

  // ── 4. Payload carries per-行 override only for the edited 題組 ─────────────

  it("submitted payload carries per-row override only for the edited 題組", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    await openConfirmation(
      "social_studies",
      { count: 2, text_instruction: "請求層次指示" },
      onSubmit,
    );

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q1ta = textInstructionTextarea(q1);

    await act(async () => {
      fireEvent.change(q1ta, { target: { value: "第一題組覆寫" } });
    });

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    const rows = JSON.parse(submitted.per_question_params as string) as Array<
      Record<string, unknown>
    >;

    // 題組 0 (第1題) must carry the override
    expect(rows[0].text_instruction).toBe("第一題組覆寫");
    // 題組 1 (第2題) must NOT carry a text_instruction override
    expect(rows[1].text_instruction).toBeUndefined();
  });

  // ── 5. Preview refetch reflects the edit ────────────────────────────────────

  it("refetches 提示詞預覽 after a per-題組 text_instruction edit", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    previewGenerateMock.mockResolvedValue({ prompts: [] });

    await openConfirmation("social_studies", {
      count: 2,
      text_instruction: "舊指示",
    });

    // Wait for the initial preview call to settle
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    await act(async () => {
      fireEvent.change(textInstructionTextarea(q1), {
        target: { value: "新指示" },
      });
    });

    // The edit triggers a debounced preview refetch
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2), {
      timeout: 3000,
    });
  });

  // ── 6. NS parity ────────────────────────────────────────────────────────────

  it("(natural_sciences) prefills each 題組 textarea with the request-level text_instruction", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    resolveGenerateMock.mockImplementation(makeResolveStub("natural_sciences"));

    await openConfirmation("natural_sciences", {
      count: 2,
      text_instruction: "請聚焦科學能力二",
    });

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q2 = within(screen.getByRole("region", { name: "第2題" }));

    expect(textInstructionTextarea(q1).value).toBe("請聚焦科學能力二");
    expect(textInstructionTextarea(q2).value).toBe("請聚焦科學能力二");
  });

  it("(natural_sciences) editing 題組 1 does not affect 題組 2 and payload carries override only for edited row", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    resolveGenerateMock.mockImplementation(makeResolveStub("natural_sciences"));

    const onSubmit = vi.fn();
    await openConfirmation(
      "natural_sciences",
      { count: 2, text_instruction: "NS請求層次" },
      onSubmit,
    );

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    const q2 = within(screen.getByRole("region", { name: "第2題" }));

    await act(async () => {
      fireEvent.change(textInstructionTextarea(q1), {
        target: { value: "NS覆寫第一題組" },
      });
    });

    // Sibling unaffected
    expect(textInstructionTextarea(q2).value).toBe("NS請求層次");

    // Submit and verify payload
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    const rows = JSON.parse(submitted.per_question_params as string) as Array<
      Record<string, unknown>
    >;
    expect(rows[0].text_instruction).toBe("NS覆寫第一題組");
    expect(rows[1].text_instruction).toBeUndefined();
  });

  // ── 7 & 8. Form-level isolation: editing one 題組's confirmation field must
  // NOT change (a) the submitted request-level text_instruction, or (b) the
  // form's own 文本出題指示 input value after returning, or the saved draft. ────

  it("submitted request-level text_instruction is unchanged after editing 題組 1's confirmation field", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();

    await openConfirmation(
      "social_studies",
      { count: 2, text_instruction: "請求層次指示" },
      onSubmit,
    );

    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    await act(async () => {
      fireEvent.change(textInstructionTextarea(q1), {
        target: { value: "確認頁覆寫文字" },
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    // The per-row override is in per_question_params[0].text_instruction, but
    // the request-level text_instruction must remain the original value.
    expect(submitted.text_instruction).toBe("請求層次指示");
  });

  it("form's 文本出題指示 input and draft are unchanged after editing 題組 1's confirmation field and returning", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    // Sign in so the draft is persisted to localStorage.
    signInAsTeacher();

    render(
      <ParamForm
        subject="social_studies"
        initialParams={{ count: 2, text_instruction: "請求層次指示" }}
        onSubmit={vi.fn()}
        disabled={false}
      />,
    );
    await screen.findByRole("button", { name: "產生" });

    // Trigger a draft save: type in the topic field so hasUserEditedRef is set.
    vi.useFakeTimers();
    fireEvent.change(
      screen.getByPlaceholderText("例如：氣候變遷與都市規劃"),
      { target: { value: "草稿觸發主題" } },
    );
    await act(async () => { vi.advanceTimersByTime(1_000); });
    vi.useRealTimers();

    // The draft now exists and must contain the original text_instruction.
    const draftBefore = JSON.parse(
      localStorage.getItem(DRAFT_KEY) ?? "null",
    ) as { fields: { textInstruction: string; topic: string } } | null;
    // If draft was written, it carries the original value.
    if (draftBefore !== null) {
      expect(draftBefore.fields.textInstruction).toBe("請求層次指示");
    }

    // Open the confirmation screen.
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    // Edit 題組 1's per-question text_instruction on the confirmation screen.
    const q1 = within(screen.getByRole("region", { name: "第1題" }));
    await act(async () => {
      fireEvent.change(textInstructionTextarea(q1), {
        target: { value: "確認頁覆寫文字" },
      });
    });

    // The draft must NOT be contaminated by the confirmation-screen edit.
    const draftAfterEdit = localStorage.getItem(DRAFT_KEY);
    if (draftAfterEdit !== null) {
      expect(draftAfterEdit).not.toContain("確認頁覆寫文字");
      const parsed = JSON.parse(draftAfterEdit) as { fields: { textInstruction: string } };
      expect(parsed.fields.textInstruction).toBe("請求層次指示");
    }

    // Return to the form.
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));

    // The form's own 文本出題指示 input (an <input> in the form, not a <textarea>
    // on the confirmation screen) must show the original request-level value.
    const formInput = screen.getByLabelText("文本出題指示") as HTMLInputElement;
    expect(formInput.value).toBe("請求層次指示");
  });
});
