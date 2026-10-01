/**
 * Issue #943 — model substitution notice in HistoryDetail.
 *
 * Tests:
 *   ms1 — notice rendered when params_json.model_substitutions is non-empty
 *   ms2 — notice absent when params_json.model_substitutions is empty / absent
 *   ms3 — shows each substituted tier with requested → ran labels
 *   ms4 — handleRegenerate strips model_substitutions from prefillParams
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail: string;
    constructor(_status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.detail = detail;
    }
  },
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: vi.fn(),
}));

vi.mock("../components/ReferenceExampleRecordSection", () => ({
  default: () => null,
}));

vi.mock("../components/QuestionCard", () => ({
  default: ({ question }: { question: { id?: string } }) => (
    <div data-testid="qc">{question?.id ?? ""}</div>
  ),
}));

vi.mock("../components/FigurePolicyTrailTimeline", () => ({
  default: () => null,
}));

import HistoryDetail from "./HistoryDetail";

function LocationSpy() {
  const loc = useLocation();
  return <div data-testid="loc-state">{JSON.stringify(loc.state ?? null)}</div>;
}

function makeDetail(params_json: Record<string, unknown> = {}, question_json: unknown = { id: "q1" }) {
  return {
    id: "rec-1",
    subject: "math",
    question_id: "q1",
    created_at: "2026-10-01T00:00:00Z",
    params_json,
    question_json,
    generation_log_id: null,
    status: "completed",
  };
}

describe("HistoryDetail model substitution notice (issue #943)", () => {
  it("ms1: shows substitution notice when model_substitutions is non-empty", async () => {
    getDetailMock.mockResolvedValueOnce(
      makeDetail({
        subject: "math",
        grade: 8,
        model_substitutions: {
          execute: { requested: "claude-fable-5-1", ran: "claude-opus-4-6" },
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={["/history/rec-1"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="rec-1" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());

    expect(
      screen.getByTestId("history-model-substitutions-notice"),
    ).toBeInTheDocument();
  });

  it("ms2: no substitution notice when model_substitutions absent", async () => {
    getDetailMock.mockResolvedValueOnce(
      makeDetail({ subject: "math", grade: 8 }),
    );

    render(
      <MemoryRouter initialEntries={["/history/rec-1"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="rec-1" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());

    expect(
      screen.queryByTestId("history-model-substitutions-notice"),
    ).not.toBeInTheDocument();
  });

  it("ms3: shows tier label and requested→ran text for each substitution", async () => {
    getDetailMock.mockResolvedValueOnce(
      makeDetail({
        subject: "math",
        grade: 8,
        model_substitutions: {
          execute: { requested: "claude-fable-5-1", ran: "claude-opus-4-6" },
          verify: { requested: "claude-fable-5-1", ran: "claude-opus-4-6" },
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={["/history/rec-1"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="rec-1" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());

    const notice = screen.getByTestId("history-model-substitutions-notice");
    // Should mention both substituted tiers
    expect(notice.textContent).toContain("claude-fable-5-1");
    expect(notice.textContent).toContain("claude-opus-4-6");
  });

  it("ms4: handleRegenerate strips model_substitutions from prefillParams", async () => {
    getDetailMock.mockResolvedValueOnce(
      makeDetail({
        subject: "math",
        grade: 8,
        model_execute: "claude-fable-5-1",
        model_substitutions: {
          execute: { requested: "claude-fable-5-1", ran: "claude-opus-4-6" },
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={["/history/rec-1"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="rec-1" />} />
          <Route path="/generate/math" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Reload saved parameters/i }));

    await waitFor(() =>
      expect(screen.getByTestId("loc-state")).toBeInTheDocument(),
    );

    const state = JSON.parse(screen.getByTestId("loc-state").textContent ?? "null");
    expect(state).not.toBeNull();
    // prefillParams must not contain model_substitutions
    expect(state.prefillParams).toBeDefined();
    expect(state.prefillParams.model_substitutions).toBeUndefined();
    // other params must be preserved
    expect(state.prefillParams.grade).toBe(8);
    expect(state.prefillParams.model_execute).toBe("claude-fable-5-1");
  });
});
