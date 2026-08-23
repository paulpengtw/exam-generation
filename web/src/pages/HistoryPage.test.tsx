import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: { email: string } | null }) => unknown) =>
    selector({ user: { email: "u@example.com" } }),
}));

const listHistoryMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  listHistory: listHistoryMock,
}));

import HistoryPage from "./HistoryPage";

describe("HistoryPage (list mode)", () => {
  it("renders rows returned by listHistory", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 2,
      items: [
        {
          id: "id-1",
          subject: "social_studies",
          question_id: "ss_1",
          created_at: "2026-07-15T00:00:00Z",
          preview: "全球暖化與都市規劃",
          verified: true,
        },
        {
          id: "id-2",
          subject: "math",
          question_id: "q_1",
          created_at: "2026-07-14T00:00:00Z",
          preview: "一元一次方程式",
          verified: false,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByText("全球暖化與都市規劃")).toBeInTheDocument(),
    );
    expect(screen.getByText("一元一次方程式")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("shows the empty-state message when the API returns no items", async () => {
    listHistoryMock.mockResolvedValueOnce({ total: 0, items: [] });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No past generations yet/i),
      ).toBeInTheDocument(),
    );
  });

  it("renders a failed row with a Failed badge and error preview", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 1,
      items: [
        {
          id: "failed-id",
          subject: "social_studies",
          question_id: "",
          created_at: "2026-07-16T00:00:00Z",
          status: "failed",
          error: "Question generation failed (RuntimeError)",
          preview: "Question generation failed (RuntimeError)",
          verified: false,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Failed")).toBeInTheDocument());
    expect(
      screen.getByText("Question generation failed (RuntimeError)"),
    ).toBeInTheDocument();
  });

  it("renders an aborted row with its own badge and preview note", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 2,
      items: [
        {
          id: "failed-id",
          subject: "social_studies",
          question_id: "",
          created_at: "2026-07-16T00:00:00Z",
          status: "failed",
          error: "Question generation failed (RuntimeError)",
          preview: "Question generation failed (RuntimeError)",
          verified: false,
        },
        {
          id: "aborted-id",
          subject: "social_studies",
          question_id: "",
          created_at: "2026-07-16T00:01:00Z",
          status: "aborted",
          error: null,
          preview: "aborted",
          verified: false,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Aborted")).toBeInTheDocument());
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Generation aborted by the user.")).toBeInTheDocument();
    expect(screen.getByText("Aborted")).toHaveClass("bg-amber-100", "text-amber-800");
    expect(screen.getByText("Failed")).toHaveClass("bg-red-100", "text-red-700");
  });
});
