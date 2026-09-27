/**
 * HistoryDetail ODT export behavior (issue #753).
 *
 * Tests that:
 * (h1) ODT download succeeds and calls saveBlob (createObjectURL called)
 * (h2) ZIP failure → InlineFailureNotice shown, no download
 * (h3) Retry re-uses the same snapshot (captureFromHistorySnapshot not called again)
 * (h4) Generation evidence fields on the snapshot are unchanged after failure
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi, type MockedFunction } from "vitest";
import type { QuestionSnapshot } from "../utils/exportSnapshot";

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const getDetailMock = vi.hoisted(() => vi.fn());
const buildOdtFromSnapshotsMock = vi.hoisted(() => vi.fn());
const captureFromHistorySnapshotMock = vi.hoisted(() => vi.fn());

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

vi.mock("../utils/odt", () => ({
  buildOdtFromSnapshots: buildOdtFromSnapshotsMock,
  formatTimestamp: () => "2026-09-27T00-00-00",
}));

vi.mock("../utils/exportSnapshot", async () => {
  const actual = await vi.importActual<typeof import("../utils/exportSnapshot")>(
    "../utils/exportSnapshot",
  );
  return {
    ...actual,
    captureFromHistorySnapshot: captureFromHistorySnapshotMock,
  };
});

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: { id: string } | null }) => unknown) =>
    selector({ user: { id: "user1" } }),
}));

vi.mock("../lib/recovery/recoveryStore", () => ({
  initRecoveryStore: vi.fn(),
  initRecoveryStoreAsync: vi.fn().mockResolvedValue(undefined),
  useRecoveryStore: (selector: (s: { pending: null; discardRecovery: () => void }) => unknown) =>
    selector({ pending: null, discardRecovery: vi.fn() }),
}));

vi.mock("../lib/recovery/storage", () => ({
  peekTabId: () => null,
  getOrCreateTabId: vi.fn().mockResolvedValue("tab-1"),
  detectTabCollision: vi.fn().mockResolvedValue(false),
  startTabCollisionListener: vi.fn().mockReturnValue(() => undefined),
  resetTabIdForCollision: vi.fn(),
}));

vi.mock("../components/QuestionCard", () => ({
  default: ({ question }: { question: { id?: string } }) => (
    <div data-testid="question-card-content" data-question-id={question?.id}>
      {question?.id ?? "no-id"}
    </div>
  ),
}));

vi.mock("../components/FigurePolicyTrailTimeline", () => ({ default: () => null }));
vi.mock("../components/ReferenceExampleRecordSection", () => ({ default: () => null }));
vi.mock("../lib/workspace/useSurfaceParticipation", () => ({
  useSurfaceParticipation: vi.fn(),
}));

import HistoryDetail from "./HistoryDetail";
import type { HistoryDetail as HistoryDetailPayload } from "../api/client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeDetail(overrides: Partial<HistoryDetailPayload> = {}): HistoryDetailPayload {
  return {
    id: "history-odt-1",
    question_id: "q-history-odt",
    subject: "math",
    params_json: {},
    question_json: {
      id: "q-history-odt",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Test question"],
      正確解題分析: ["Test answer"],
    },
    verification_trail: [],
    figure_policy_trail: [],
    status: "success",
    generation_log_id: "log-1",
    reference_example_record: null,
    created_at: "2026-09-27T00:00:00Z",
    ...overrides,
  } as unknown as HistoryDetailPayload;
}

function makeSnapshot(detail: HistoryDetailPayload): QuestionSnapshot {
  const q = detail.question_json as unknown as import("../hooks/useGenerate").ExamQuestion;
  return {
    exported: {
      ...q,
      _export: {
        format_version: 1,
        exported_at: "2026-09-27T00:00:00.000Z",
        is_draft: false,
        run_id: detail.generation_log_id ?? null,
        index: null,
        content_revision: null,
        processing: "ended",
        termination_reason: "normal",
        delivery_status: "complete",
        missing: [],
        review: { status: "unknown", content_revision: null },
      },
    },
    captured: q,
    isDraft: false,
    index: null,
    imageSources: {},
  };
}

function renderDetail(recordId = "history-odt-1") {
  return render(
    <MemoryRouter initialEntries={[`/history/${recordId}`]}>
      <Routes>
        <Route path="/history/:id" element={<HistoryDetail recordId={recordId} />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("HistoryDetail ODT export — success (issue #753)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("(h1) ODT download succeeds and triggers createObjectURL", async () => {
    const detail = makeDetail();
    getDetailMock.mockResolvedValue(detail);
    const snap = makeSnapshot(detail);
    captureFromHistorySnapshotMock.mockReturnValue(snap);
    buildOdtFromSnapshotsMock.mockResolvedValue(
      new Blob(["ODT"], { type: "application/vnd.oasis.opendocument.text" }),
    );

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:history-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderDetail();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Download ODT/i })).toBeInTheDocument(),
      );

      fireEvent.click(screen.getByRole("button", { name: /Download ODT/i }));

      await waitFor(() => expect(blobs).toHaveLength(1));
      expect(createObjectURL).toHaveBeenCalledTimes(1);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

describe("HistoryDetail ODT export — ZIP failure (issue #753)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("(h2) ZIP failure shows InlineFailureNotice and does NOT call createObjectURL", async () => {
    const detail = makeDetail();
    getDetailMock.mockResolvedValue(detail);
    const snap = makeSnapshot(detail);
    captureFromHistorySnapshotMock.mockReturnValue(snap);
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip packaging failure"));

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:should-not-be-called");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderDetail();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Download ODT/i })).toBeInTheDocument(),
      );

      fireEvent.click(screen.getByRole("button", { name: /Download ODT/i }));

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
      expect(screen.getByRole("alert")).toHaveTextContent(/Unable/i);
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

describe("HistoryDetail ODT export — retry uses same snapshot (issue #753)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("(h3) Retry after ZIP failure re-uses the snapshot, does not re-capture", async () => {
    const detail = makeDetail();
    getDetailMock.mockResolvedValue(detail);
    const snap = makeSnapshot(detail);
    captureFromHistorySnapshotMock.mockReturnValue(snap);

    // First call: fail
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip fail"));
    // Second call (retry): succeed
    buildOdtFromSnapshotsMock.mockResolvedValue(
      new Blob(["ODT"], { type: "application/vnd.oasis.opendocument.text" }),
    );

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:retry-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderDetail();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Download ODT/i })).toBeInTheDocument(),
      );

      // First click: fail
      fireEvent.click(screen.getByRole("button", { name: /Download ODT/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      const captureCallsBefore = (captureFromHistorySnapshotMock as MockedFunction<typeof captureFromHistorySnapshotMock>).mock.calls.length;

      // Click Retry
      fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
      await waitFor(() => expect(blobs).toHaveLength(1));

      // captureFromHistorySnapshot must NOT have been called again (snapshot reused)
      const captureCallsAfter = (captureFromHistorySnapshotMock as MockedFunction<typeof captureFromHistorySnapshotMock>).mock.calls.length;
      expect(captureCallsAfter).toBe(captureCallsBefore);

      // The retry passed the same snapshot to buildOdtFromSnapshots
      const [, snapshotsOnRetry] = buildOdtFromSnapshotsMock.mock.calls[1] as [
        string,
        QuestionSnapshot[],
      ];
      expect(snapshotsOnRetry).toHaveLength(1);
      expect(snapshotsOnRetry[0]).toBe(snap);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });

  it("(h4) ODT failure does not alter the snapshot _export fields", async () => {
    const detail = makeDetail();
    getDetailMock.mockResolvedValue(detail);
    const snap = makeSnapshot(detail);
    const evidenceBefore = JSON.stringify(snap.exported._export);
    captureFromHistorySnapshotMock.mockReturnValue(snap);
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip fail"));

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:never");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderDetail();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Download ODT/i })).toBeInTheDocument(),
      );

      fireEvent.click(screen.getByRole("button", { name: /Download ODT/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Evidence unchanged
      expect(JSON.stringify(snap.exported._export)).toBe(evidenceBefore);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});
