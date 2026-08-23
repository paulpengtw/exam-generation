import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

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

vi.mock("../components/QuestionCard", () => ({
  default: ({
    question,
    recordId,
    phase,
    isFinal,
  }: {
    question: { id?: string };
    recordId?: string;
    phase?: string;
    isFinal?: boolean;
  }) => (
    <div
      data-testid="qc"
      data-record-id={recordId}
      data-phase={phase}
      data-final={String(isFinal)}
    >
      {question?.id ?? ""}
    </div>
  ),
}));

import HistoryDetail from "./HistoryDetail";

function LocationSpy() {
  const loc = useLocation();
  return (
    <div data-testid="loc-state">{JSON.stringify(loc.state ?? null)}</div>
  );
}

describe("HistoryDetail", () => {
  it("renders the stored question and calls the download API", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8 },
      question_json: { id: "ss_1", 核心問題: "核心" },
    });
    downloadMock.mockResolvedValueOnce(new Blob(["{}"], { type: "application/json" }));

    render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toHaveTextContent("ss_1"));

    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith("abc"));
  });

  it("regenerate button navigates to /generate/<subject> with params in router state", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8, topic: "climate" },
      question_json: { id: "ss_1" },
    });

    render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
          <Route path="/generate/social_studies" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Re-run in generator/i }))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Re-run in generator/i }));

    await waitFor(() =>
      expect(screen.getByTestId("loc-state").textContent).toContain(
        '"topic":"climate"',
      ),
    );
  });

  it("uses the latest record identity returned by history detail for the card", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "latest-id",
      subject: "social_studies",
      question_id: "ss-child",
      created_at: "2026-07-16T00:00:00Z",
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-child", verification: { passed: true } },
    });

    render(
      <MemoryRouter initialEntries={["/history/old-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="old-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("qc")).toHaveAttribute("data-record-id", "latest-id");
    });
    expect(screen.getByTestId("qc")).toHaveAttribute("data-final", "true");
  });

  it("renders failed detail params and error without question content or download", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "failed-id",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-07-16T00:00:00Z",
      status: "failed",
      error: "Question generation failed (RuntimeError)",
      params_json: { subject: "social_studies", topic: "climate" },
      question_json: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/failed-id"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="failed-id" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.getByText("Question generation failed (RuntimeError)"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/"topic": "climate"/)).toBeInTheDocument();
    expect(screen.queryByTestId("qc")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Download JSON/i }),
    ).not.toBeInTheDocument();
  });
});
