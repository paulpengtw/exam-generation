/**
 * Tests for ReferenceExampleRecordSection in HistoryDetail (REAL component, not mocked).
 * For interrupted (failed/aborted) details, the section is rendered directly
 * in the failed/aborted panel, allowing us to test it without mocking QuestionCard.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
const downloadMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: downloadMock,
}));

// Mock QuestionCard but NOT ReferenceExampleRecordSection
vi.mock("../components/QuestionCard", () => ({
  default: ({ question }: { question: { id?: string } }) => (
    <div data-testid="qc">{question?.id ?? ""}</div>
  ),
}));

import HistoryDetail from "./HistoryDetail";

const _entry = () => ({
  code: "reference_example",
  kind: "example",
  question_id: "hd-ref",
  stage: "generator",
  slot: null,
  description: "test ref example",
  source: "/some/path/few_shot.json",
  timestamp: "2026-09-10T00:00:00Z",
});

function renderDetail(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/history/${id}`]}>
      <Routes>
        <Route path="/history/:id" element={<HistoryDetail recordId={id} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HistoryDetail 參考範例紀錄 section (real component)", () => {
  it("failed detail with a record shows collapsed header with count", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "failed-with-record",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-09-10T00:00:00Z",
      status: "failed",
      error: "generation failed",
      params_json: { subject: "social_studies" },
      question_json: null,
      reference_example_record: {
        disabled: false,
        entries: [_entry()],
      },
    });

    renderDetail("failed-with-record");

    // Section should be present with toggle button showing count "1"
    const toggleBtn = await screen.findByRole("button", {
      name: "Show reference examples used during generation",
    });
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn.textContent).toBe("1");

    // Entries not visible until expanded
    expect(screen.queryByText("test ref example")).not.toBeInTheDocument();

    // Click to expand
    fireEvent.click(toggleBtn);
    expect(screen.getByText(/test ref example/)).toBeInTheDocument();
  });

  it("failed detail with reference_example_record null shows no-record line", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "failed-null-record",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-09-10T00:00:00Z",
      status: "failed",
      error: "generation failed",
      params_json: { subject: "social_studies" },
      question_json: null,
      reference_example_record: null,
    });

    renderDetail("failed-null-record");

    await waitFor(() =>
      expect(screen.getByText("No reference examples were recorded.")).toBeInTheDocument(),
    );
  });

  it("aborted detail with disabled record shows disabled line", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "aborted-disabled",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-09-10T00:00:00Z",
      status: "aborted",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: null,
      reference_example_record: { disabled: true, entries: [] },
    });

    renderDetail("aborted-disabled");

    await waitFor(() =>
      expect(
        screen.getByText("Reference examples were turned off for this run."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText("No reference examples were recorded."),
    ).not.toBeInTheDocument();
  });
});
