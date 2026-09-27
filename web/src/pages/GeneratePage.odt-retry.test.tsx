/**
 * GeneratePage batch ODT retry behavior (issue #753).
 *
 * Tests that:
 * (r1) ZIP failure → InlineFailureNotice shown, no download (createObjectURL not called)
 * (r2) Retry re-uses the same captured snapshot even if a new revision arrived
 * (r3) A fresh click after dismissal captures a new snapshot
 * (r4) Generation evidence (completeness/processing/review) is unchanged after ODT failure
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi, type MockedFunction } from "vitest";
import type { QuestionSnapshot } from "../utils/exportSnapshot";

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const useGenerateMock = vi.hoisted(() => vi.fn());
const buildOdtFromSnapshotsMock = vi.hoisted(() => vi.fn());
const captureBatchSnapshotsMock = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: useGenerateMock,
}));

vi.mock("../utils/odt", () => ({
  buildOdtFromSnapshots: buildOdtFromSnapshotsMock,
  formatTimestamp: () => "2026-09-27T00-00-00",
}));

// Partial mock: keep real captureBatch (for JSON download) but intercept captureBatchSnapshots
vi.mock("../utils/exportSnapshot", async () => {
  const actual = await vi.importActual<typeof import("../utils/exportSnapshot")>(
    "../utils/exportSnapshot",
  );
  return {
    ...actual,
    captureBatchSnapshots: captureBatchSnapshotsMock,
  };
});

vi.mock("../lib/generationStream", async () => {
  const actual = await vi.importActual<typeof import("../lib/generationStream")>("../lib/generationStream");
  return {
    ...actual,
    projectGenerationCardEvidence: () => ({}),
    projectGenerationEvidence: () => null,
  };
});

vi.mock("../components/ParamForm", () => ({ default: () => <div data-testid="param-form" /> }));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/GenerationStatusBar", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: false, open: vi.fn() }),
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));
vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { user: null; logoutExplicit: () => void }) => unknown) =>
    selector({ user: null, logoutExplicit: vi.fn() }),
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useLocation: () => ({ pathname: "/generate/math", state: null }),
    useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
  };
});

import GeneratePage from "./GeneratePage";
import type { GeneratedQuestion, ExamQuestion } from "../hooks/useGenerate";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQuestion(id: string, content: string): ExamQuestion {
  return {
    id,
    情境: ["個人"],
    題型種類: "single",
    題型: "選擇題",
    題目: [content],
    正確解題分析: ["answer"],
  };
}

function makeDisplayResult(q: ExamQuestion, idx: number): GeneratedQuestion {
  return {
    index: idx,
    question: q,
    phase: "verified" as const,
    isFinal: true,
    stableId: q.id,
    contentRevision: 1,
  };
}

/** Minimal QuestionSnapshot stub for testing */
function makeSnapshot(q: ExamQuestion): QuestionSnapshot {
  return {
    exported: {
      ...q,
      _export: {
        format_version: 1,
        exported_at: "2026-09-27T00:00:00.000Z",
        is_draft: false,
        run_id: null,
        index: 0,
        content_revision: 1,
        processing: "ended",
        termination_reason: "normal",
        delivery_status: "complete",
        missing: [],
        review: { status: "unknown", content_revision: null },
      },
    },
    captured: q,
    isDraft: false,
    index: 0,
    imageSources: {},
  };
}

// ---------------------------------------------------------------------------
// Shared setup
// ---------------------------------------------------------------------------

const q1 = makeQuestion("q-retry-1", "Question content v1");
const displayResults: GeneratedQuestion[] = [makeDisplayResult(q1, 0)];

function setupMocks() {
  localStorage.clear();
  sessionStorage.clear();

  useGenerateMock.mockReturnValue({
    status: "done",
    progressLines: [],
    results: [q1],
    displayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: 1,
    finishedAt: 2,
    generationLogId: null,
    subQuestionTotal: null,
    resultsCompletion: "complete",
    terminalEvidence: true,
    evidence: null,
    generate: vi.fn(),
    restoreResults: vi.fn(),
    reset: vi.fn(),
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/generate/math"]}>
      <Routes>
        <Route path="/generate/math" element={<GeneratePage subject="math" />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// (r1) ZIP failure → error shown, no download
// ---------------------------------------------------------------------------

describe("GeneratePage batch ODT — ZIP failure (issue #753)", () => {
  beforeEach(() => {
    setupMocks();
    vi.clearAllMocks();
  });

  it("(r1) ZIP failure shows InlineFailureNotice and does NOT call createObjectURL", async () => {
    const snap = makeSnapshot(q1);
    captureBatchSnapshotsMock.mockReturnValue([[snap], false]);
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip packaging failure"));

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:should-not-be-called");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));

      await waitFor(() =>
        expect(screen.getByRole("alert")).toBeInTheDocument(),
      );

      // Error message displayed
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Unable to generate the batch ODT file/i,
      );

      // No download initiated
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (r2) Retry re-uses the same captured snapshot
// ---------------------------------------------------------------------------

describe("GeneratePage batch ODT — retry uses same snapshot (issue #753)", () => {
  beforeEach(() => {
    setupMocks();
    vi.clearAllMocks();
  });

  it("(r2) clicking Retry after ZIP failure re-uses the snapshot captured on the first click", async () => {
    const snap = makeSnapshot(q1);
    captureBatchSnapshotsMock.mockReturnValue([[snap], false]);

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
      renderPage();

      // First click: fail
      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Reset mock call count tracker before retry
      const captureCallsBefore = (captureBatchSnapshotsMock as MockedFunction<typeof captureBatchSnapshotsMock>).mock.calls.length;

      // Click Retry
      fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
      await waitFor(() => expect(blobs).toHaveLength(1));

      // captureBatchSnapshots must NOT have been called again (snapshot reused)
      const captureCallsAfter = (captureBatchSnapshotsMock as MockedFunction<typeof captureBatchSnapshotsMock>).mock.calls.length;
      expect(captureCallsAfter).toBe(captureCallsBefore);

      // The retry passed the same snapshot to buildOdtFromSnapshots
      const [, snapshotsOnRetry] = buildOdtFromSnapshotsMock.mock.calls[1] as [
        string,
        QuestionSnapshot[],
      ];
      expect(snapshotsOnRetry).toHaveLength(1);
      expect(snapshotsOnRetry[0]).toBe(snap); // same object reference
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (r3) Fresh click after dismiss captures a new snapshot
// ---------------------------------------------------------------------------

describe("GeneratePage batch ODT — fresh click captures new snapshot (issue #753)", () => {
  beforeEach(() => {
    setupMocks();
    vi.clearAllMocks();
  });

  it("(r3) after dismiss, a fresh ODT click captures a new snapshot (not the old one)", async () => {
    const snapV1 = makeSnapshot(q1);
    const q1v2 = makeQuestion("q-retry-1", "Question content v2");
    const snapV2 = makeSnapshot(q1v2);

    // First click: return v1 snapshot
    captureBatchSnapshotsMock.mockReturnValueOnce([[snapV1], false]);
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip fail first"));

    // After dismiss and new click: return v2 snapshot
    captureBatchSnapshotsMock.mockReturnValueOnce([[snapV2], false]);
    buildOdtFromSnapshotsMock.mockResolvedValueOnce(
      new Blob(["ODT"], { type: "application/vnd.oasis.opendocument.text" }),
    );

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:new-click-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderPage();

      // First click: fail
      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Dismiss the failure notice
      fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());

      // Second fresh click
      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));
      await waitFor(() => expect(blobs).toHaveLength(1));

      // The new click used the new snapshot (v2), not v1
      const [, snapshotsOnNew] = buildOdtFromSnapshotsMock.mock.calls[1] as [
        string,
        QuestionSnapshot[],
      ];
      expect(snapshotsOnNew).toHaveLength(1);
      expect(snapshotsOnNew[0]).toBe(snapV2);
      expect(snapshotsOnNew[0]).not.toBe(snapV1);

      // captureBatchSnapshots was called twice (once per fresh click)
      expect(captureBatchSnapshotsMock).toHaveBeenCalledTimes(2);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (r4) Generation evidence unchanged after ODT failure
// ---------------------------------------------------------------------------

describe("GeneratePage batch ODT — evidence unchanged after failure (issue #753)", () => {
  beforeEach(() => {
    setupMocks();
    vi.clearAllMocks();
  });

  it("(r4) ODT ZIP failure does not alter the captured snapshot _export fields", async () => {
    const snap = makeSnapshot(q1);
    const evidenceBefore = JSON.stringify(snap.exported._export);

    captureBatchSnapshotsMock.mockReturnValue([[snap], false]);
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip fail"));

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:never");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // The snapshot _export must be unchanged
      expect(JSON.stringify(snap.exported._export)).toBe(evidenceBefore);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});
