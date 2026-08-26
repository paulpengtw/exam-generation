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

  it("marks a history row when its trail records a shipped figure-kind collision", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 1,
      items: [
        {
          id: "degraded-id",
          subject: "social_studies",
          question_id: "ss-degraded",
          created_at: "2026-07-15T00:00:00Z",
          preview: "圖像種類碰撞",
          verified: true,
          figure_policy_trail: [
            {
              code: "figure_policy",
              kind: "warning",
              question_id: "ss-degraded",
              message: "duplicate image shipped",
              duplicate_image_shipped: true,
              left: "題幹",
              right: "小題 1",
              effective_figure_kind: "地圖",
              timestamp: "2026-08-25T00:00:00Z",
            },
          ],
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
      expect(screen.getByText("Figure-kind diversity degraded")).toBeInTheDocument(),
    );
  });

  it("does not mark a history row when its trail says no duplicate was shipped", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 1,
      items: [
        {
          id: "clean-id",
          subject: "social_studies",
          question_id: "ss-clean",
          created_at: "2026-07-15T00:00:00Z",
          preview: "乾淨結果",
          verified: true,
          figure_policy_trail: [
            {
              code: "figure_policy",
              kind: "warning",
              question_id: "ss-clean",
              message: "repair completed without shipping a duplicate",
              duplicate_image_shipped: false,
              left: "題幹",
              right: "小題 1",
              effective_figure_kind: "地圖",
              timestamp: "2026-08-25T00:00:00Z",
            },
          ],
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

    await waitFor(() => expect(screen.getByText("乾淨結果")).toBeInTheDocument());
    expect(screen.queryByText("Figure-kind diversity degraded")).not.toBeInTheDocument();
  });

  it("marks a history row when its trail records a data inconsistency", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 1,
      items: [
        {
          id: "data-degraded-id",
          subject: "social_studies",
          question_id: "ss-data-degraded",
          created_at: "2026-07-15T00:00:00Z",
          preview: "跨圖資料矛盾",
          verified: true,
          figure_policy_trail: [
            {
              code: "figure_policy",
              kind: "data_inconsistency",
              question_id: "ss-data-degraded",
              left: "題幹",
              right: "小題 1",
              series: "石油",
              x: 1990,
              left_value: 38,
              right_value: 10,
              conflicting_values: { 題幹: 38, "小題 1": 10 },
              unit: "%",
              duplicate_image_shipped: true,
              message: "cross-figure data inconsistency",
              timestamp: "2026-08-25T00:00:00Z",
            },
          ],
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
      expect(screen.getByText("Figure-kind diversity degraded")).toBeInTheDocument(),
    );
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
