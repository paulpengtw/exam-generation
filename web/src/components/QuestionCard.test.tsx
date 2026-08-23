import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const recordFigureFallbackMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: recordFigureFallbackMock,
}));

vi.stubGlobal("fetch", fetchMock);

import QuestionCard from "./QuestionCard";
import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const question: ExamQuestion = {
  id: "q_test",
  情境: ["Personal"],
  題型種類: "Single question",
  題型: "Multiple choice",
  數學思考: ["Reasoning"],
  學習內容: [{ 編碼: "N-7-1", 說明: "Numbers" }],
  題目: ["What is 2 + 2?"],
  正確解題分析: ["2 + 2 = 4."],
};

describe("QuestionCard draft rendering", () => {
  it("marks draft cards, shows available solution content, and disables downloads", () => {
    render(<QuestionCard question={question} phase="draft" isFinal={false} />);

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download ODT" })).toBeDisabled();
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  fetchMock.mockReset();
});

describe("QuestionCard + FigureRenderer swap", () => {
  it("renders the PNG img when VITE_ENABLE_FRONTEND_TS_RENDERER is unset", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["a"], rows: [["1"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders the FigureRenderer when the flag is on and the spec is supported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["時段"], rows: [["9:00"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    // The PNG <img> should not be rendered in the diagram slot when the TS renderer took over.
    expect(screen.queryByAltText("Question diagram")).toBeNull();
  });

  it("falls back to the PNG img when the flag is on but the spec is unsupported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const spec = { render_mode: "chart", chart_type: "histogram", data: {} };
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: spec,
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByAltText("Question diagram")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(recordFigureFallbackMock).toHaveBeenCalledWith(spec);
  });
});

const ssSub: SubQuestion = {
  id: "sq1",
  序號: 1,
  年級: 8,
  科目: ["地理"],
  核心素養: ["社-J-A2"],
  學習內容: [],
  學習表現: [],
  出題概念: "",
  題型: "選擇題",
  題目: "Question asks (A) x (B) y (C) z (D) w",
  答案: "B",
  答案解析: "…",
  評分規準: [],
  誘答分析: {
    A: "誤讀題意",
    B: "正確答案：y。",
    C: "概念混淆",
    D: "過度推論",
  },
};

const ssQuestion: ExamQuestion = {
  id: "ss1",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "core?",
  文本: "Shared passage",
  subquestions: [ssSub],
  題目: ["passage", ssSub.題目],
  正確解題分析: ["B"],
  verification: { passed: true },
};

function getSelectionField(fieldPath: string): HTMLElement {
  const field = document.querySelector<HTMLElement>(`[data-selection-field="${fieldPath}"]`);
  if (!field) throw new Error(`Missing selection field ${fieldPath}`);
  return field;
}

function getOnlyTextNode(element: HTMLElement): Text {
  const textNode = element.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected a field to contain one text node");
  return textNode;
}

function selectRange(
  startElement: HTMLElement,
  startOffset: number,
  endElement: HTMLElement = startElement,
  endOffset: number = startOffset,
): void {
  const range = document.createRange();
  range.setStart(getOnlyTextNode(startElement), startOffset);
  range.setEnd(getOnlyTextNode(endElement), endOffset);

  const selection = window.getSelection();
  if (!selection) throw new Error("jsdom did not provide a Selection");
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent(document, new Event("selectionchange"));
  fireEvent.mouseUp(startElement);
}

describe("QuestionCard 圈選 capture", () => {
  it("captures a within-field DOM Range as one segment with its field path, offsets, and quote", () => {
    render(<QuestionCard question={ssQuestion} isFinal />);

    const passage = getSelectionField("文本");
    selectRange(passage, 7, passage, 14);

    const chip = screen.getByRole("listitem");
    expect(chip).toHaveAttribute("data-field-path", "文本");
    expect(chip).toHaveAttribute("data-start", "7");
    expect(chip).toHaveAttribute("data-end", "14");
    expect(chip).toHaveAttribute("data-quoted-text", "passage");
  });

  it("splits a cross-boundary DOM Range into ordered per-field segments", () => {
    render(<QuestionCard question={ssQuestion} isFinal />);

    selectRange(
      getSelectionField("文本"),
      7,
      getSelectionField("subquestions[0].題目"),
      8,
    );

    const chips = screen.getAllByRole("listitem");
    expect(chips).toHaveLength(2);
    expect(chips.map((chip) => chip.getAttribute("data-field-path"))).toEqual([
      "文本",
      "subquestions[0].題目",
    ]);
    expect(chips.map((chip) => [
      chip.getAttribute("data-start"),
      chip.getAttribute("data-end"),
      chip.getAttribute("data-quoted-text"),
    ])).toEqual([
      ["7", "14", "passage"],
      ["0", "8", "Question"],
    ]);
  });

  it("rejects a chrome-only selection with user feedback and no empty chip", () => {
    render(<QuestionCard question={ssQuestion} isFinal />);

    const passageLabel = screen.getByText("Passage", { exact: true });
    selectRange(passageLabel, 0, passageLabel, "Passage".length);

    expect(screen.getByRole("alert")).toHaveTextContent("Select exam content to add a selection.");
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("renders each captured 圈選 as a visible annotation chip", () => {
    render(<QuestionCard question={ssQuestion} isFinal />);

    const passage = getSelectionField("文本");
    selectRange(passage, 7, passage, 14);

    expect(screen.getByRole("list", { name: "Selections" })).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("passage");
  });

  it("gives each captured 圈選 an editable 修改指示 and deletes its chip and note together", () => {
    render(<QuestionCard question={ssQuestion} recordId="record-422" isFinal />);

    selectRange(getSelectionField("文本"), 7, getSelectionField("文本"), 14);

    const instruction = screen.getByRole("textbox", {
      name: "Modification instruction 1",
    });
    expect(instruction).toHaveValue("");

    fireEvent.change(instruction, { target: { value: "Fix the wording" } });
    expect(instruction).toHaveValue("Fix the wording");

    fireEvent.click(screen.getByRole("button", { name: "Delete selection 1" }));

    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Modification instruction 1" }))
      .not.toBeInTheDocument();
  });

  it("keeps submit disabled with no selections or any missing 修改指示", () => {
    render(<QuestionCard question={ssQuestion} recordId="record-422" isFinal />);

    const submit = screen.getByRole("button", { name: "Submit modifications" });
    expect(submit).toBeDisabled();

    selectRange(getSelectionField("文本"), 7, getSelectionField("文本"), 14);
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "   " },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix the passage" },
    });
    expect(submit).not.toBeDisabled();

    selectRange(
      getSelectionField("subquestions[0].題目"),
      0,
      getSelectionField("subquestions[0].題目"),
      8,
    );
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 2" }), {
      target: { value: "Fix the subquestion" },
    });
    expect(submit).not.toBeDisabled();
  });

  it("posts the exact per-圈選 payload with field-addressed segments and 修改指示", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    render(<QuestionCard question={ssQuestion} recordId="record-422" isFinal />);

    selectRange(getSelectionField("文本"), 7, getSelectionField("文本"), 14);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix the passage" },
    });

    selectRange(
      getSelectionField("subquestions[0].題目"),
      0,
      getSelectionField("subquestions[0].題目"),
      8,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 2" }), {
      target: { value: "Fix the subquestion" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/generation-records/record-422/modifications");
    expect(options.method).toBe("POST");
    expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(options.body))).toEqual({
      annotations: [
        {
          segments: [
            { field_path: "文本", start: 7, end: 14, quoted_text: "passage" },
          ],
          修改指示: "Fix the passage",
        },
        {
          segments: [
            {
              field_path: "subquestions[0].題目",
              start: 0,
              end: 8,
              quoted_text: "Question",
            },
          ],
          修改指示: "Fix the subquestion",
        },
      ],
    });
  });

  it("does not expose capture UI for generating or failed cards", () => {
    const { unmount } = render(<QuestionCard question={ssQuestion} phase="draft" isFinal={false} />);
    expect(document.querySelector("[data-selection-field]"))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Selections" })).not.toBeInTheDocument();
    unmount();

    const failedQuestion = { ...ssQuestion, verification: { passed: false } };
    render(<QuestionCard question={failedQuestion} isFinal />);
    expect(document.querySelector("[data-selection-field]"))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Selections" })).not.toBeInTheDocument();
  });
});

describe("QuestionCard distractor panel", () => {
  it("renders 誘答分析 rows inside a subquestion when the dict is non-empty", () => {
    render(<QuestionCard question={ssQuestion} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText("誤讀題意")).toBeInTheDocument();
    expect(screen.getByText(/正確答案：y/)).toBeInTheDocument();
  });

  it("does not render the toggle button when 誘答分析 is empty", () => {
    const emptySub: SubQuestion = { ...ssSub, 誘答分析: {} };
    const empty: ExamQuestion = { ...ssQuestion, subquestions: [emptySub] };
    render(<QuestionCard question={empty} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    expect(screen.queryByRole("button", { name: "Show Distractor Analysis" })).not.toBeInTheDocument();
  });

  it("renders 誘答分析 on math flat questions", () => {
    const mathQ: ExamQuestion = {
      ...question,
      誘答分析: { A: "誤讀題意", B: "正確答案：4。", C: "x", D: "y" },
    };
    render(<QuestionCard question={mathQ} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Solution" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText(/正確答案：4/)).toBeInTheDocument();
  });
});
