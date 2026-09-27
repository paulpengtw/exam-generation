import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const recordFigureFallbackMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());
const buildExamOdtMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: recordFigureFallbackMock,
}));
vi.mock("../utils/odt", () => ({
  buildExamOdt: buildExamOdtMock,
  formatTimestamp: () => "test-time",
}));

vi.stubGlobal("fetch", fetchMock);

import QuestionCard from "./QuestionCard";
import type {
  ExamQuestion,
  SubQuestion,
  FigurePolicyTrailEntry,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { QuestionEvidence } from "../lib/generationEvidence";

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
  it("marks draft cards, shows available solution content, enables JSON and disables ODT/PNG", () => {
    // issue #751: JSON download is available for drafts; ODT/PNG remain disabled
    render(<QuestionCard question={question} phase="draft" isFinal={false} />);

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    // JSON download is enabled for drafts (labeled "Download Draft JSON")
    expect(screen.getByRole("button", { name: "Download Draft JSON" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Download ODT" })).toBeDisabled();
  });

  it("surfaces a per-card ODT failure without replacing the export label", async () => {
    buildExamOdtMock.mockRejectedValueOnce(new Error("zip failed"));
    render(<QuestionCard question={question} isFinal />);

    fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to generate the ODT file.",
    );
    const button = screen.getByRole("button", { name: "Download ODT" });
    expect(button).toHaveAttribute("data-action-state", "failed");
    expect(button).toHaveTextContent("Download ODT");
  });

  it("shows a shared-spinner phase chip for an in-flight batch card and removes it when final", () => {
    const { rerender } = render(
      <QuestionCard
        question={question}
        phase="draft"
        isFinal={false}
        requestedTotal={2}
        livePhaseLabel="Text"
      />,
    );

    const phaseChip = screen.getByTestId("question-card-live-phase");
    expect(phaseChip).toHaveTextContent("Text");
    expect(phaseChip.querySelector(".feedback-spinner")).toBeInTheDocument();
    expect(phaseChip.querySelector(".sentry-unmask")).toHaveTextContent("Text");
    expect(screen.getByText("Draft")).toBeInTheDocument();

    rerender(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal
        requestedTotal={2}
        livePhaseLabel="Text"
      />,
    );

    expect(screen.queryByTestId("question-card-live-phase")).not.toBeInTheDocument();
  });
});

describe("QuestionCard Agent 自主驗證修正歷程", () => {
  const trail: VerificationTrailEntry[] = [
    {
      code: "verification_trail",
      kind: "verification",
      question_id: "q_test",
      passed: true,
      details: "The answer and explanation agree.",
      my_answer: "A",
      provided_answer: "A",
      answer_match: true,
      chart_verification: null,
      model: "verify-model",
      timestamp: "2026-01-01T00:00:00+00:00",
    },
    {
      code: "verification_trail",
      kind: "verification",
      question_id: "q_test",
      passed: false,
      details: "The supplied answer conflicts with the question.",
      my_answer: "B",
      provided_answer: "A",
      answer_match: false,
      chart_verification: null,
      model: "verify-model",
      timestamp: "2026-01-01T00:01:00+00:00",
    },
  ];

  it("is collapsed by default and expands to show passed and failed verdicts", () => {
    render(<QuestionCard question={question} trail={trail} isFinal />);

    const toggle = screen.getByRole("button", {
      name: "Show Agent autonomous verification and correction history",
    });
    expect(screen.queryByText("The answer and explanation agree.")).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The answer and explanation agree.")).toBeInTheDocument();
    expect(screen.getByText("The supplied answer conflicts with the question.")).toBeInTheDocument();
  });

  it("mounts a rejected correction as retained history without an applied diff", () => {
    const retainedSnapshot = {
      id: "q_test",
      題目: ["retained question"],
      答案: "B",
    };
    const rejectedTrail: VerificationTrailEntry[] = [
      {
        code: "verification_trail",
        kind: "initial",
        question_id: "q_test",
        timestamp: "2026-01-01T00:00:00+00:00",
        snapshot: retainedSnapshot,
      },
      {
        code: "verification_trail",
        kind: "correction",
        question_id: "q_test",
        retry_index: 1,
        model: "correct-model",
        timestamp: "2026-01-01T00:01:00+00:00",
        outcome: "rejected",
        reason: {
          code: "subquestion_structure_mismatch",
          path: "subquestions",
          message: "The correction omitted an original sub-question.",
        },
        snapshot: retainedSnapshot,
      },
    ];

    render(<QuestionCard question={question} trail={rejectedTrail} isFinal />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(screen.getByText("Correction rejected")).toBeInTheDocument();
    expect(screen.getByText("Retained question snapshot")).toBeInTheDocument();
    expect(screen.queryByText("Changed fields")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show before and after snapshots" }),
    ).not.toBeInTheDocument();
  });
});

describe("QuestionCard 圖像種類降級警告", () => {
  it("shows a warning banner naming the colliding 題幹/小題 pair and 圖像種類", () => {
    const figurePolicyTrail: FigurePolicyTrailEntry[] = [
      {
        code: "figure_policy",
        kind: "warning",
        question_id: "ss-policy",
        message: "duplicate image shipped",
        duplicate_image_shipped: true,
        left: "題幹",
        right: "小題 1",
        effective_figure_kind: "地圖",
        timestamp: "2026-08-25T00:00:00+00:00",
      },
    ];

    render(
      <QuestionCard
        question={question}
        figurePolicyTrail={figurePolicyTrail}
        isFinal
      />,
    );

    const banner = screen.getByRole("alert", {
      name: "Figure-kind degradation warning",
    });
    expect(banner).toHaveTextContent("題幹");
    expect(banner).toHaveTextContent("小題 1");
    expect(banner).toHaveTextContent("地圖");
  });

  it("does not render degradation UI for a warning that did not ship a duplicate", () => {
    const figurePolicyTrail: FigurePolicyTrailEntry[] = [
      {
        code: "figure_policy",
        kind: "warning",
        question_id: "ss-clean",
        message: "repair completed without shipping a duplicate",
        duplicate_image_shipped: false,
        left: "題幹",
        right: "小題 1",
        effective_figure_kind: "地圖",
        timestamp: "2026-08-25T00:00:00+00:00",
      },
    ];

    render(
      <QuestionCard
        question={question}
        figurePolicyTrail={figurePolicyTrail}
        isFinal
      />,
    );

    expect(
      screen.queryByRole("alert", { name: "Figure-kind degradation warning" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Figure-kind warning")).not.toBeInTheDocument();
  });

  it("shows a cross-figure data inconsistency as a degradation warning", () => {
    const figurePolicyTrail: FigurePolicyTrailEntry[] = [
      {
        code: "figure_policy",
        kind: "data_inconsistency",
        question_id: "ss-data-warning",
        left: "題幹",
        right: "小題 1",
        series: "石油",
        x: 1990,
        left_value: 38,
        right_value: 10,
        conflicting_values: { 題幹: 38, "小題 1": 10 },
        unit: "%",
        duplicate_image_shipped: true,
        message: "Warning: cross-figure data inconsistency for 石油",
        timestamp: "2026-08-25T00:00:00+00:00",
      },
    ];

    render(
      <QuestionCard
        question={question}
        figurePolicyTrail={figurePolicyTrail}
        isFinal
      />,
    );

    expect(
      screen.getByRole("alert", { name: "Figure-kind degradation warning" }),
    ).toHaveTextContent("cross-figure data inconsistency");
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

describe("QuestionCard figure freshness", () => {
  it("renders the image out-of-sync warning only when image_stale is set", () => {
    const staleQuestion = {
      ...question,
      image_stale: true,
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    const { rerender } = render(<QuestionCard question={staleQuestion} isFinal />);

    expect(screen.getByText("Image may be out of sync")).toBeInTheDocument();

    rerender(<QuestionCard question={question} isFinal />);
    expect(screen.queryByText("Image may be out of sync")).not.toBeInTheDocument();
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

const mathGroup: ExamQuestion = {
  id: "math-group",
  情境: ["科學"],
  題型種類: "題組題",
  題型: "選擇題",
  數學思考: ["運用"],
  核心素養: ["數-J-A2"],
  學習內容: [{ 編碼: "N-8-1", 說明: "parent content" }],
  學習表現: [{ 編碼: "n-IV-2", 說明: "parent performance" }],
  核心問題: "math core",
  文本: "math passage",
  subquestions: [{
    id: "math-group-sq1",
    序號: 1,
    年級: 8,
    題型: "選擇題",
    題目: "math subquestion",
    答案: "4",
    答案解析: "math explanation",
    學習內容: [{ 編碼: "N-8-1", 說明: "sub content" }],
    學習表現: [{ 編碼: "n-IV-2", 說明: "sub performance" }],
    出題概念: "",
  }],
  題目: [],
  正確解題分析: [],
};

describe("QuestionCard math 題組", () => {
  it("renders parent competency/performance and subquestion answers without social-only fields", () => {
    render(<QuestionCard question={mathGroup} isFinal />);

    expect(screen.getByText("數-J-A2", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("n-IV-2", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getByText("math core", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("math subquestion", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("地理", { exact: true })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    expect(screen.getByText("4", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("math explanation", { exact: true })).toBeInTheDocument();
  });
});

describe("QuestionCard fixed social-studies slots", () => {
  it("renders a missing middle slot and partial delivery evidence without compacting survivors", () => {
    const thirdSub: SubQuestion = { ...ssSub, id: "ss1-sq003", 序號: 3, 題目: "Third question" };
    const partialQuestion = { ...ssQuestion, subquestions: [ssSub, thirdSub] };
    const evidence: QuestionEvidence = {
      questionId: "ss1",
      index: 0,
      processing: "ended",
      content: { receipt: "final", revision: 3, question: partialQuestion, phase: "verified" },
      terminal: {
        termination_reason: "normal",
        has_final: true,
        final_revision: 3,
        delivery_status: "partial",
        expected: [
          { kind: "subquestion", question_id: "ss1", subquestion_id: "ss1-sq001", subquestion_index: 0 },
          { kind: "subquestion", question_id: "ss1", subquestion_id: "ss1-sq002", subquestion_index: 1 },
          { kind: "subquestion", question_id: "ss1", subquestion_id: "ss1-sq003", subquestion_index: 2 },
        ],
        delivered: [
          { kind: "subquestion", question_id: "ss1", subquestion_id: "ss1-sq001", subquestion_index: 0 },
          { kind: "subquestion", question_id: "ss1", subquestion_id: "ss1-sq003", subquestion_index: 2 },
        ],
        missing: [
          {
            kind: "subquestion",
            question_id: "ss1",
            subquestion_id: "ss1-sq002",
            subquestion_index: 1,
            reason: "subquestion not delivered",
          },
        ],
        review: { status: "skipped", content_revision: 3 },
      },
      finalPending: false,
      finalMissing: false,
      review: { status: "skipped", revision: 3 },
      trail: [],
      figurePolicyTrail: [],
      referenceExampleRecord: undefined,
    };

    render(<QuestionCard question={partialQuestion} evidence={evidence} isFinal />);

    expect(screen.getByTestId("evidence-delivery-status")).toHaveTextContent("部分");
    expect(screen.getByTestId("missing-subquestion-2")).toHaveTextContent("Sub-question unavailable");
    expect(screen.getByText("Third question")).toBeInTheDocument();
    expect(screen.getByText("Q3題")).toBeInTheDocument();
  });
});

describe("QuestionCard rubric eras and legacy display", () => {
  it("renders legacy axis tags for a legacy social-studies record", () => {
    const legacy: ExamQuestion = {
      ...ssQuestion,
      id: "ss-legacy-axes",
      閱讀歷程: ["legacy process"],
      文本形式: "legacy text form",
    };

    render(<QuestionCard question={legacy} isFinal />);

    expect(screen.getByText("legacy process", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("legacy text form", { exact: true })).toBeInTheDocument();
  });

  it("renders legacy axis tags for a flat legacy record", () => {
    const legacy: ExamQuestion = {
      ...ssQuestion,
      id: "ss-flat-legacy-axes",
      subquestions: [],
      閱讀歷程: ["flat legacy process"],
      文本形式: "flat legacy text form",
    };

    render(<QuestionCard question={legacy} isFinal />);

    expect(screen.getByText("flat legacy process", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("flat legacy text form", { exact: true })).toBeInTheDocument();
  });

  it("renders ICCS tags and suppresses stale legacy tags for a new record", () => {
    const knowing = "Knowing–Defining and Describing";
    const current: ExamQuestion = {
      ...ssQuestion,
      id: "ss-current-axes",
      內容領域: "Civic Principles",
      認知歷程: [knowing],
      閱讀歷程: ["stale legacy process"],
      文本形式: "stale legacy text form",
    };

    render(<QuestionCard question={current} isFinal />);

    expect(screen.getByText("Civic Principles", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(knowing, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("stale legacy process", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("stale legacy text form", { exact: true })).not.toBeInTheDocument();
  });

  it("renders native 0..N rubric levels and their examples as text", () => {
    const question: ExamQuestion = {
      ...ssQuestion,
      id: "ss-native-rubric",
      subquestions: [{
        ...ssSub,
        評分規準: [
          { code: "0", 規準說明: "No credit", 學生作答實例: ["Blank"] },
          { code: "1", 規準說明: "Partial credit", 學生作答實例: ["Partly correct"] },
          { code: "2", 規準說明: "Full credit", 學生作答實例: ["Correct"] },
          { code: "3", 規準說明: "Advanced", 學生作答實例: ["Thorough"] },
        ],
      }],
    };

    render(<QuestionCard question={question} isFinal />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));

    for (const text of [
      "0", "No credit", "1", "Partial credit", "2", "Full credit", "3", "Advanced",
    ]) {
      expect(screen.getByText(text, { exact: true })).toBeInTheDocument();
    }
  });

  it("renders legacy rubric codes and a retired legacy question type read-only", () => {
    const question: ExamQuestion = {
      ...ssQuestion,
      id: "ss-legacy-rubric",
      subquestions: [{
        ...ssSub,
        題型: "封閉式建構反應題",
        評分規準: [
          { code: "2", 規準說明: "Legacy full credit" },
          { code: "1", 規準說明: "Legacy partial credit" },
          { code: "0", 規準說明: "Legacy no credit" },
          { code: "0X", 規準說明: "Legacy unanswered" },
        ],
      }],
    };

    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByText("封閉式建構反應題", { exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));

    for (const text of [
      "2", "Legacy full credit", "1", "Legacy partial credit",
      "0", "Legacy no credit", "0X", "Legacy unanswered",
    ]) {
      expect(screen.getByText(text, { exact: true })).toBeInTheDocument();
    }
  });
});

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

function rejectionResponse(error: string, message: string): Response {
  return new Response(JSON.stringify({ error, message }), {
    status: 422,
    headers: { "Content-Type": "application/json" },
  });
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

  it("renders the frozen field and suggested alternative from a structured rejection", async () => {
    fetchMock.mockResolvedValueOnce(
      rejectionResponse(
        "frozen_field",
        "The field '核心問題' is fixed by the corrector; regenerate the record or change the request settings.",
      ),
    );
    render(<QuestionCard question={ssQuestion} recordId="record-419" isFinal />);

    selectRange(getSelectionField("文本"), 7, getSelectionField("文本"), 14);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix the passage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-error-code", "frozen_field");
    expect(alert).toHaveTextContent("核心問題");
    expect(alert).toHaveTextContent("regenerate the record or change the request settings");
  });

  it("marks stale-base rejections with warning severity", async () => {
    fetchMock.mockResolvedValueOnce(
      rejectionResponse(
        "stale_base",
        "The selected text for '文本' no longer matches this record.",
      ),
    );
    render(<QuestionCard question={ssQuestion} recordId="record-419" isFinal />);

    selectRange(getSelectionField("文本"), 7, getSelectionField("文本"), 14);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix the passage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-error-code", "stale_base");
    expect(alert).toHaveAttribute("data-severity", "warning");
  });

  it("preserves every annotation after rejection and resubmits after deleting the offending selection", async () => {
    fetchMock
      .mockResolvedValueOnce(
        rejectionResponse(
          "frozen_field",
          "The field '核心問題' is fixed by the corrector; regenerate the record or change the request settings.",
        ),
      )
      .mockResolvedValueOnce(
        new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    render(<QuestionCard question={ssQuestion} recordId="record-419" isFinal />);

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
    await screen.findByRole("alert");

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" }))
      .toHaveValue("Fix the passage");
    expect(screen.getByRole("textbox", { name: "Modification instruction 2" }))
      .toHaveValue("Fix the subquestion");

    fireEvent.click(screen.getByRole("button", { name: "Delete selection 1" }));
    expect(screen.getByRole("button", { name: "Submit modifications" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const [, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(options.body))).toEqual({
      annotations: [
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

describe("QuestionCard — positionUnknown (issue #750)", () => {
  it("shows position-unknown badge when positionUnknown is true", () => {
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        positionUnknown={true}
      />,
    );

    expect(screen.getByTestId("question-card-position-unknown")).toBeInTheDocument();
  });

  it("does not show 原題序未知 badge when positionUnknown is false", () => {
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        positionUnknown={false}
      />,
    );

    expect(screen.queryByTestId("question-card-position-unknown")).not.toBeInTheDocument();
  });

  it("does not show 原題序未知 badge when positionUnknown is absent", () => {
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
      />,
    );

    expect(screen.queryByTestId("question-card-position-unknown")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Issue #751: snapshot immutability — newer revision after click
// ---------------------------------------------------------------------------

describe("QuestionCard JSON export snapshot immutability (issue #751)", () => {
  it("keeps captured revision and exported_at even when evidence changes after click", async () => {
    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:snap";
      });
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);

    const baseQuestion: import("../hooks/useGenerate").ExamQuestion = {
      id: "qSnap",
      情境: ["個人"],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Revision 3 content"],
      正確解題分析: ["Answer R3"],
    };

    const evidence3: import("../lib/generationEvidence").QuestionEvidence = {
      questionId: "qSnap",
      index: 0,
      processing: "ended",
      content: {
        receipt: "final",
        revision: 3,
        question: baseQuestion,
        phase: "verified",
      },
      terminal: {
        termination_reason: "normal",
        has_final: true,
        final_revision: 3,
        delivery_status: "complete",
        expected: [],
        delivered: [],
        missing: [],
        review: { status: "passed", content_revision: 3 },
      },
      terminalConflict: false,
      terminalConflictReason: undefined,
      reviewConflict: false,
      contentConflict: false,
      contentConflictReason: undefined,
      finalPending: false,
      finalMissing: false,
      review: { status: "passed", revision: 3 },
      trail: [],
      figurePolicyTrail: [],
      referenceExampleRecord: undefined,
      activity: { operations: {}, calls: {} },
    };

    try {
      const { rerender } = render(
        <QuestionCard
          question={baseQuestion}
          evidence={evidence3}
          isFinal={true}
          runId="run-snap"
        />,
      );

      // Click Download JSON — snapshot captured at revision 3
      fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));

      // Simulate newer revision arriving AFTER click but before Blob is consumed
      const updatedQuestion = {
        ...baseQuestion,
        題目: ["Revision 4 content — should NOT appear in export"],
      };
      const evidence4 = {
        ...evidence3,
        content: { ...evidence3.content, revision: 4, question: updatedQuestion },
        terminal: {
          ...evidence3.terminal!,
          final_revision: 4,
        },
        review: { status: "passed" as const, revision: 4 },
      };
      rerender(
        <QuestionCard
          question={updatedQuestion}
          evidence={evidence4}
          isFinal={true}
          runId="run-snap"
        />,
      );

      // Wait for the blob created by the click action
      await vi.waitFor(() => expect(blobs).toHaveLength(1));

      const body = JSON.parse(await blobs[0].text()) as Record<string, unknown>;
      const meta = body._export as Record<string, unknown>;

      // The snapshot must reflect what was captured at click time (revision 3)
      expect(meta.content_revision).toBe(3);
      expect(typeof meta.exported_at).toBe("string");
      // The question text must be revision 3's text, not revision 4
      expect(body["題目"]).toEqual(["Revision 3 content"]);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});
