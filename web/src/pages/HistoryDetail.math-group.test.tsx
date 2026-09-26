import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const getDetailMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: vi.fn(),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import HistoryDetail from "./HistoryDetail";

function persistedMathGroup(): Record<string, unknown> {
  const result = readFileSync(
    resolve(__dirname, "../../../tests/fixtures/generation_v2/math_groups_interleaved.jsonl"),
    "utf-8",
  )
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as { event: string; payload: Record<string, unknown> })
    .find((line) => line.event === "result" && line.payload.id === "q_RUN_001");

  if (!result) throw new Error("math fixture result not found");
  return result.payload;
}

describe("HistoryDetail math 題組", () => {
  it("renders the persisted math group with parent and per-subquestion metadata", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "math-history",
      subject: "math",
      question_id: "q_RUN_001",
      created_at: "2026-09-26T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "math" },
      question_json: persistedMathGroup(),
      verification_trail: null,
      figure_policy_trail: [],
      reference_example_record: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/math-history"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="math-history" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("核心問題 A", { exact: true })).toBeInTheDocument();
    });

    expect(screen.getByText("文本 A", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("形成", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("A-8-6", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("s-IV-15", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getByText("A 小題 1", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("A 小題 3", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("8年級", { exact: true })).toHaveLength(2);
    expect(screen.getAllByText("是非題", { exact: true })).toHaveLength(3);

    fireEvent.click(screen.getAllByRole("button", { name: "Show Answer" })[0]);
    expect(screen.getAllByText("A", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getByText("解析", { exact: true })).toBeInTheDocument();
  });
});
