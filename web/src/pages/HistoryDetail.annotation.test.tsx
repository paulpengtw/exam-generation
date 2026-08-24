import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.stubGlobal("fetch", fetchMock);

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getHistoryDetail: getDetailMock,
  };
});

import HistoryDetail from "./HistoryDetail";

const verifiedHistoryQuestion = {
  id: "history-question",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  閱讀歷程: ["Legacy reading process"],
  文本形式: "Legacy text form",
  核心問題: "A verified core question",
  文本: "A passage that can be selected",
  subquestions: [
    {
      id: "sub-1",
      序號: 1,
      年級: 8,
      科目: ["地理"],
      核心素養: ["社-J-A2"],
      學習內容: [],
      學習表現: [],
      出題概念: "",
      題型: "選擇題",
      題目: "A subquestion",
      答案: "B",
      答案解析: "Because B.",
      評分規準: [],
    },
  ],
  題目: ["A passage that can be selected", "A subquestion"],
  正確解題分析: ["B is correct."],
  verification: { passed: true },
};

function historyPayload() {
  return {
    id: "history-record",
    subject: "social_studies",
    question_id: "history-question",
    created_at: "2026-07-16T00:00:00Z",
    status: "completed",
    error: null,
    params_json: { subject: "social_studies" },
    question_json: verifiedHistoryQuestion,
  };
}

function renderHistoryDetail() {
  return render(
    <MemoryRouter initialEntries={["/history/history-record"]}>
      <Routes>
        <Route
          path="/history/:id"
          element={<HistoryDetail recordId="history-record" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function selectPassage(): void {
  const field = screen.getByText("A passage that can be selected", { exact: true });
  const textNode = field.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected passage text node");
  const range = document.createRange();
  range.setStart(textNode, 2);
  range.setEnd(textNode, 9);
  const selection = window.getSelection();
  if (!selection) throw new Error("jsdom did not provide a Selection");
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(field);
}

afterEach(() => {
  fetchMock.mockReset();
  getDetailMock.mockReset();
});

describe("HistoryDetail 人工審題修正 integration", () => {
  it("shows the no-trail state for a legacy history record", async () => {
    getDetailMock.mockResolvedValueOnce({
      ...historyPayload(),
      verification_trail: null,
    });

    renderHistoryDetail();

    await waitFor(() =>
      expect(
        screen.getByText(
          "No Agent autonomous verification and correction history was recorded.",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("shows functional annotation affordances for a verified history record", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());

    renderHistoryDetail();
    await waitFor(() => expect(screen.getByText("A passage that can be selected")).toBeInTheDocument());
    expect(screen.getByText("Legacy reading process", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Legacy text form", { exact: true })).toBeInTheDocument();

    selectPassage();
    const instruction = screen.getByRole("textbox", { name: "Modification instruction 1" });
    fireEvent.change(instruction, { target: { value: "Fix this wording" } });

    expect(screen.getByRole("list", { name: "Selections" })).toHaveTextContent("passage");
    expect(screen.getByRole("button", { name: "Submit modifications" })).not.toBeDisabled();
  });

  it("surfaces a not_latest_version pre-flight rejection in the history page card", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: "not_latest_version",
          message: "This record is not the latest version; submit from the newest record.",
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderHistoryDetail();
    await waitFor(() => expect(screen.getByText("A passage that can be selected")).toBeInTheDocument());
    selectPassage();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Modification instruction 1" }),
      { target: { value: "Fix this wording" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-error-code", "not_latest_version");
    expect(alert).toHaveTextContent("This record is not the latest version");
  });
});
