/**
 * Issue #939 — HistoryDetail shows missing-slot state for stored partial records.
 *
 * Tests:
 * - A stored partial record with a missing image slot → card shows 【圖片缺項】 marker
 *   (via MissingSubQuestionBlock / evidence prop with synthetic terminal).
 * - An old record without terminal_delivery → card renders unchanged (complete).
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));
vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: null }) => unknown) =>
    selector({ user: null }),
}));
vi.mock("../lib/recovery/storage", () => ({
  peekTabId: () => null,
  getOrCreateTabId: () => "test-tab",
  detectTabCollision: () => Promise.resolve(false),
  startTabCollisionListener: () => () => undefined,
  resetTabIdForCollision: () => undefined,
}));
vi.mock("../lib/recovery/recoveryStore", () => ({
  initRecoveryStore: () => undefined,
  initRecoveryStoreAsync: () => Promise.resolve(undefined),
  useRecoveryStore: (selector: (s: { pending: null; claimedSnapshotId: null }) => unknown) =>
    selector({ pending: null, claimedSnapshotId: null }),
  discardRecovery: () => undefined,
}));
vi.mock("../lib/workspace/useSurfaceParticipation", () => ({
  useSurfaceParticipation: () => undefined,
}));
vi.mock("../utils/exportSnapshot", () => ({
  captureFromHistory: () => null,
  captureFromHistorySnapshot: () => null,
  augmentWithDomMarkup: () => undefined,
  singleQuestionOdtFilename: () => "test.odt",
}));
vi.mock("../utils/odt", () => ({ buildOdtFromSnapshots: vi.fn() }));
vi.mock("../utils/domCapture", () => ({ serializeElementToMarkup: () => "" }));
vi.mock("../lib/recovery/modificationValidation", () => ({
  validateModificationBase: () => ({ valid: true }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail: string;
    status: number;
    constructor(status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.detail = detail;
      this.status = status;
    }
  },
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: vi.fn(),
}));

vi.mock("../components/FigurePolicyTrailTimeline", () => ({
  default: () => null,
}));
vi.mock("../components/ReferenceExampleRecordSection", () => ({
  default: () => null,
}));

// Use the REAL QuestionCard (not mocked) so we can test the missing-slot rendering.
// Import after all mocks are set up.
import HistoryDetail from "./HistoryDetail";

function renderDetail(recordId = "rec-001") {
  return render(
    <MemoryRouter initialEntries={[`/history/${recordId}`]}>
      <Routes>
        <Route path="/history/:recordId" element={<HistoryDetail recordId={recordId} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const BASE_DETAIL = {
  id: "rec-001",
  subject: "natural_sciences",
  question_id: "q_NS_001",
  created_at: "2026-10-01T00:00:00Z",
  status: "completed" as const,
  error: null,
  generation_log_id: null,
  params_json: {},
  question_json: {
    id: "q_NS_001",
    核心問題: "What is photosynthesis?",
    題型種類: "題組題",
    subquestions: [
      { id: "q_NS_001-sq001", 序號: 1, 題目: "Question 1", 答案: "A", 答案解析: "..." },
    ],
  },
  verification_trail: null,
  figure_policy_trail: null,
  reference_example_record: null,
};

describe("HistoryDetail card state for partial records (issue #939)", () => {
  it("old record without terminal_delivery renders card without missing-slot markers", async () => {
    getDetailMock.mockResolvedValueOnce({
      ...BASE_DETAIL,
      terminal_delivery: null,
    });
    renderDetail();
    // Wait for QuestionCard to appear (the question content)
    await waitFor(() => {
      expect(screen.queryByText("What is photosynthesis?")).not.toBeNull();
    }, { timeout: 3000 });
    // No missing-subquestion markers
    expect(screen.queryByTestId("missing-subquestion-1")).toBeNull();
    expect(screen.queryByTestId("missing-subquestion-2")).toBeNull();
  });

  it("partial record with missing image slot shows MissingSubQuestionBlock marker", async () => {
    getDetailMock.mockResolvedValueOnce({
      ...BASE_DETAIL,
      terminal_delivery: {
        delivery_status: "partial",
        termination_reason: "normal",
        missing: [
          {
            kind: "subquestion",
            question_id: "q_NS_001",
            subquestion_id: "q_NS_001-sq002",
            subquestion_index: 1,
            reason: "subquestion not delivered",
          },
        ],
      },
    });
    renderDetail();
    // Wait for the card to load
    await waitFor(() => {
      expect(screen.queryByText("What is photosynthesis?")).not.toBeNull();
    }, { timeout: 3000 });
    // Should see the missing-subquestion marker for slot 2 (subquestion_index=1 → slot 2)
    await waitFor(() => {
      expect(screen.queryByTestId("missing-subquestion-2")).not.toBeNull();
    }, { timeout: 3000 });
  });
});
