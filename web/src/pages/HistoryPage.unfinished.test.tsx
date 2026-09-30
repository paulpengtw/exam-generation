/**
 * Tests for the 「尚未結束」 unfinished-runs section in HistoryPage (issue #913).
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: { id: string; email: string } | null }) => unknown) =>
    selector({ user: { id: "user-1", email: "u@example.com" } }),
}));

const listHistoryMock = vi.hoisted(() => vi.fn());
const listRunsMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail: string;
    constructor(_status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.detail = detail;
    }
  },
  listHistory: listHistoryMock,
  listRuns: listRunsMock,
}));

vi.mock("../lib/historyBadge", () => ({
  initLastSeenAt: vi.fn().mockReturnValue("2020-01-01T00:00:00Z"),
  setLastSeenAt: vi.fn(),
  getLastSeenAt: vi.fn().mockReturnValue("2020-01-01T00:00:00Z"),
  findNewestCompletedAt: vi.fn().mockReturnValue(null),
}));

import HistoryPage from "./HistoryPage";

const EMPTY_HISTORY = { total: 0, items: [] };

function renderHistory() {
  return render(
    <MemoryRouter initialEntries={["/history"]}>
      <Routes>
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/generate" element={<div>GeneratePage</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HistoryPage – 尚未結束 section", () => {
  beforeEach(() => {
    listHistoryMock.mockResolvedValue(EMPTY_HISTORY);
  });

  it("shows section with queued run and position text", async () => {
    listRunsMock.mockResolvedValue([
      {
        run_id: "run-1",
        status: "queued",
        subject: "math",
        started_at: null,
        completed_at: null,
        queue_position: 2,
        cancel_requested: false,
      },
    ]);
    renderHistory();
    await waitFor(() =>
      expect(screen.getByText("尚未結束")).toBeInTheDocument(),
    );
    expect(screen.getByText("排隊中 · 前面還有 2 個")).toBeInTheDocument();
  });

  it("shows running label for a running run", async () => {
    listRunsMock.mockResolvedValue([
      {
        run_id: "run-2",
        status: "running",
        subject: "social_studies",
        started_at: "2026-10-01T00:00:00Z",
        completed_at: null,
        queue_position: null,
        cancel_requested: false,
      },
    ]);
    renderHistory();
    await waitFor(() =>
      expect(screen.getByText("生成中")).toBeInTheDocument(),
    );
  });

  it("shows cancelling label when cancel_requested is true", async () => {
    listRunsMock.mockResolvedValue([
      {
        run_id: "run-3",
        status: "running",
        subject: "math",
        started_at: "2026-10-01T00:00:00Z",
        completed_at: null,
        queue_position: null,
        cancel_requested: true,
      },
    ]);
    renderHistory();
    await waitFor(() =>
      expect(screen.getByText("取消中")).toBeInTheDocument(),
    );
  });

  it("hides section when all runs are terminal", async () => {
    // listRuns returns only ended runs → none are active → section hidden
    listRunsMock.mockResolvedValue([
      {
        run_id: "run-4",
        status: "completed",
        subject: "math",
        started_at: "2026-10-01T00:00:00Z",
        completed_at: "2026-10-01T01:00:00Z",
        queue_position: null,
        cancel_requested: false,
      },
    ]);
    renderHistory();
    // Allow polling to settle
    await waitFor(() =>
      expect(listRunsMock).toHaveBeenCalled(),
    );
    expect(screen.queryByText("尚未結束")).not.toBeInTheDocument();
  });

  it("links to /generate/<subject>?run=<id> for known subjects", async () => {
    listRunsMock.mockResolvedValue([
      {
        run_id: "abc123",
        status: "running",
        subject: "math",
        started_at: null,
        completed_at: null,
        queue_position: null,
        cancel_requested: false,
      },
    ]);
    renderHistory();
    await waitFor(() =>
      expect(screen.getByText("生成中")).toBeInTheDocument(),
    );
    const link = screen.getByRole("link", { name: /abc123|math/ });
    expect(link).toHaveAttribute("href", "/generate/math?run=abc123");
  });

  it("falls back to /generate when subject is null", async () => {
    listRunsMock.mockResolvedValue([
      {
        run_id: "run-no-subject",
        status: "running",
        subject: null,
        started_at: null,
        completed_at: null,
        queue_position: null,
        cancel_requested: false,
      },
    ]);
    renderHistory();
    await waitFor(() =>
      expect(screen.getByText("生成中")).toBeInTheDocument(),
    );
    const link = screen.getByRole("link", { name: /run-no-subject/ });
    expect(link).toHaveAttribute("href", "/generate");
  });

  it("refetches history list when run transitions from active to ended", async () => {
    // First poll: run is active
    listRunsMock
      .mockResolvedValueOnce([
        {
          run_id: "run-5",
          status: "running",
          subject: "math",
          started_at: null,
          completed_at: null,
          queue_position: null,
          cancel_requested: false,
        },
      ])
      // Second poll: run is gone (ended and removed from active list)
      .mockResolvedValue([]);

    listHistoryMock.mockResolvedValue(EMPTY_HISTORY);

    renderHistory();

    // Wait for first poll to register the active run
    await waitFor(() => expect(screen.getByText("生成中")).toBeInTheDocument());

    // Wait for second poll to fire (the test will use fake timers; but here
    // we just verify listHistory gets called a second time due to transition)
    await waitFor(() => {
      // listHistory should be called more than once — initial load + refetch
      expect(listHistoryMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    }, { timeout: 8000 });
  });
});
