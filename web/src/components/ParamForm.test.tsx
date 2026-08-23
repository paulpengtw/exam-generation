import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } })));
const tMock = vi.hoisted(() => {
  const messages: Record<string, string> = {
    "history.prefill_notice": "Some saved parameters are no longer available in the current schema.",
    "form.grade": "Grade",
    "form.difficulty": "Difficulty",
    "form.text_word_limit": "文本字數限制",
    "form.unlimited": "不限",
    "form.subject_filter": "科目",
    "form.subject_filter_natural_sciences": "依科目篩選學習內容選項",
    "form.subject_filter_natural_sciences_help": "此選擇僅篩選學習內容選項，不會作為出題參數送出。",
    "form.core_question_callback": "末小題回扣核心問題",
    "form.btn_generate": "Generate",
    "form.btn_confirm_send": "Confirm",
    "form.error_set_type_required": "題型種類 is required.",
  };
  return (key: string) => messages[key] ?? key;
});
vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));
vi.mock("../i18n/useT", () => ({
  useT: () => tMock,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ParamForm from "./ParamForm";

const FAKE_MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "社會時事", instruction: "" },
  ],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "textbook", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const FAKE_SOCIAL_SCHEMA = {
  ...FAKE_MATH_SCHEMA,
  題型種類: [{ value: "題組題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
};

const FAKE_SCIENCE_SCHEMA = {
  ...FAKE_SOCIAL_SCHEMA,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  科目: [
    { value: "生物", instruction: "" },
    { value: "化學", instruction: "" },
  ],
  學習內容: [
    { value: "BDa-IV-1", instruction: "生物內容", 科目: "生物" },
    { value: "JFa-IV-1", instruction: "化學內容", 科目: "化學" },
    { value: "INa-IV-1", instruction: "共通內容", 科目: "" },
  ],
};

describe("ParamForm subject-filter label", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders the 學習內容 narrowing label instead of 科目 for 自然科學", async () => {
    getSchemasMock.mockResolvedValue(FAKE_SCIENCE_SCHEMA);

    render(<ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />);

    expect(await screen.findByText("依科目篩選學習內容選項", { selector: "label" })).toBeInTheDocument();
    expect(screen.queryByText("科目", { selector: "label", exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("此選擇僅篩選學習內容選項，不會作為出題參數送出。")).toBeInTheDocument();
  });

  it("keeps the 科目 label for 數學 and 社會領域", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);
    const math = render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    expect(await screen.findByText("科目", { selector: "label", exact: true })).toBeInTheDocument();
    math.unmount();

    getSchemasMock.mockResolvedValue(FAKE_SOCIAL_SCHEMA);
    render(<ParamForm subject="social_studies" onSubmit={() => {}} disabled={false} />);
    expect(await screen.findByText("科目", { selector: "label", exact: true })).toBeInTheDocument();
  });

  it("filters 自然科學 學習內容 options by the selected 科目", async () => {
    getSchemasMock.mockResolvedValue(FAKE_SCIENCE_SCHEMA);
    render(<ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />);

    const subjectOption = await screen.findByRole("option", { name: "化學" });
    // Switch to checkbox mode (default is search mode)
    fireEvent.click(screen.getByRole("button", { name: "切換勾選模式" }));
    expect(screen.getByText("BDa-IV-1")).toBeInTheDocument();
    expect(screen.getByText("JFa-IV-1")).toBeInTheDocument();
    expect(screen.getByText("INa-IV-1")).toBeInTheDocument();

    fireEvent.change(subjectOption.closest("select")!, { target: { value: "化學" } });

    await waitFor(() => expect(screen.queryByText("BDa-IV-1")).not.toBeInTheDocument());
    expect(screen.getByText("JFa-IV-1")).toBeInTheDocument();
    expect(screen.getByText("INa-IV-1")).toBeInTheDocument();
  });
});

describe("ParamForm core-question callback option", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it.each([
    ["social_studies", FAKE_SOCIAL_SCHEMA],
    ["natural_sciences", FAKE_SCIENCE_SCHEMA],
  ] as const)("renders a checked 「末小題回扣核心問題」 checkbox for %s", async (subject, schema) => {
    getSchemasMock.mockResolvedValue(schema);

    render(<ParamForm subject={subject} onSubmit={() => {}} disabled={false} />);

    expect(
      await screen.findByRole("checkbox", { name: "末小題回扣核心問題" }),
    ).toBeChecked();
  });

  it("does not render the callback checkbox for math", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    await screen.findByRole("button", { name: "Generate" });
    expect(
      screen.queryByRole("checkbox", { name: "末小題回扣核心問題" }),
    ).not.toBeInTheDocument();
  });
});

describe("ParamForm difficulty dropdown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);
  });

  it("does not send `difficulty` when left at the default option", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    // Wait for schemas to load
    await screen.findByRole("button", { name: /generate/i });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    // Confirm dialog opens; click confirm.
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBeUndefined();
  });

  it("sends `difficulty` when the user picks hard", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByRole("button", { name: /generate/i });

    const select = screen.getByLabelText(/difficulty/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "hard" } });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBe("hard");
  });
});

describe("ParamForm top-level text word limit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);
  });

  it("shows 文本字數限制 for math", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    await screen.findByRole("button", { name: /generate/i });
    expect(screen.getByLabelText("文本字數限制")).toBeInTheDocument();
  });

  it.each(["social_studies", "natural_sciences"])(
    "shows 文本字數限制 for %s",
    async (subject) => {
      render(<ParamForm subject={subject} onSubmit={() => {}} disabled={false} />);

      await screen.findByRole("button", { name: /generate/i });
      expect(screen.getByLabelText("文本字數限制")).toHaveAttribute("placeholder", "不限");
    },
  );
});

describe("ParamForm prefill", () => {
  it("initializes visible fields from initialParams", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{ grade: 8, topic: "climate change" }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByDisplayValue("climate change")).toBeInTheDocument(),
    );
    expect((screen.getByLabelText(/Grade/i) as HTMLSelectElement).value).toBe("8");
  });

  it("shows the prefill-notice when initialParams contain values not in the current schema", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{
          grade: 8,
          context: ["個人", "已刪除情境"],
          set_type: "已刪除設定",
        }}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Some saved parameters are no longer available/i),
      ).toBeInTheDocument(),
    );
  });

  it("prevents 發送前確認 when history prefill clears 題型種類", async () => {
    const onSubmit = vi.fn();
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={onSubmit}
        initialParams={{ grade: 8, set_type: "已刪除題型種類" }}
      />,
    );

    await screen.findByText(/Some saved parameters are no longer available/i);
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    expect(await screen.findByText(/題型種類.*required/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm/i })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
