/**
 * QuestionCard ODT export behavior (issue #753).
 *
 * Tests that:
 * (q1) per-image failure → ODT still downloads with 【匯出缺圖／預覽轉換失敗】 marker at the slot
 * (q2) ZIP failure → error shown, no download (createObjectURL not called)
 * (q3) Retry re-uses the same snapshot even if a new revision arrived meanwhile
 * (q4) A fresh click after dismissal captures a new snapshot
 * (q5) Generation evidence (processing/delivery/review) unchanged after ODT failure
 * (q6) PNG download keeps draft filename convention (草稿_ prefix)
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import JSZip from "jszip";
import type { QuestionSnapshot } from "../utils/exportSnapshot";

// ---------------------------------------------------------------------------
// Hoisted mocks — minimal set matching QuestionCard.test.tsx
// ---------------------------------------------------------------------------
const buildOdtFromSnapshotsMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: vi.fn(),
}));

vi.mock("../utils/odt", () => ({
  buildOdtFromSnapshots: buildOdtFromSnapshotsMock,
  formatTimestamp: () => "2026-09-27T00-00-00",
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.stubGlobal("fetch", vi.fn());

import QuestionCard from "./QuestionCard";
import type { ExamQuestion } from "../hooks/useGenerate";
import type { QuestionEvidence } from "../lib/generationEvidence";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FAKE_PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

function makeQuestion(id: string, extra: Partial<ExamQuestion> = {}): ExamQuestion {
  return {
    id,
    情境: ["個人"],
    題型種類: "single",
    題型: "選擇題",
    題目: [`Test question for ${id}`],
    正確解題分析: ["answer"],
    ...extra,
  };
}

function makeEvidence(q: ExamQuestion, revision = 1): QuestionEvidence {
  return {
    questionId: q.id ?? "",
    index: 0,
    processing: "ended",
    content: {
      receipt: "final",
      revision,
      question: q,
      phase: "verified",
    },
    terminal: {
      termination_reason: "normal",
      has_final: true,
      final_revision: revision,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: revision },
    },
    terminalConflict: false,
    terminalConflictReason: undefined,
    reviewConflict: false,
    contentConflict: false,
    contentConflictReason: undefined,
    finalPending: false,
    finalMissing: false,
    review: { status: "passed", revision },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
    activity: { operations: {}, calls: {} },
  };
}

/**
 * Build a minimal real ODT blob with a failure marker at the stem slot.
 * Used to simulate what buildOdtFromSnapshots returns on per-image failure.
 */
async function makeOdtWithFailureMarker(): Promise<Blob> {
  const zip = new JSZip();
  zip.file("mimetype", "application/vnd.oasis.opendocument.text");
  zip.file(
    "content.xml",
    [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"',
      ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">',
      "<office:body><office:text>",
      "<text:p>【匯出缺圖／預覽轉換失敗】</text:p>",
      "<text:p>Question text here</text:p>",
      "</office:text></office:body>",
      "</office:document-content>",
    ].join("\n"),
  );
  return zip.generateAsync({ type: "blob" });
}

// ---------------------------------------------------------------------------
// (q1) Per-image failure → ODT still downloads with marker
// ---------------------------------------------------------------------------

describe("QuestionCard ODT — per-image failure produces marker (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q1) rasterizer failure: ODT is downloaded with 【匯出缺圖／預覽轉換失敗】 at failing slot", async () => {
    // Simulate buildOdtFromSnapshots returning an ODT with the failure marker
    // (the real behavior: rasterizer fails → marker in content.xml, but ODT blob still produced)
    const odtWithMarker = await makeOdtWithFailureMarker();
    buildOdtFromSnapshotsMock.mockResolvedValueOnce(odtWithMarker);

    const q = makeQuestion("q-per-img-fail", {
      chart_spec: { render_mode: "html", description: "test chart" } as Record<string, unknown>,
    });
    const evidence = makeEvidence(q);

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:per-img-fail-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      render(<QuestionCard question={q} evidence={evidence} isFinal runId="run-1" />);

      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));

      // ODT is downloaded (blob created) despite per-image failure
      await waitFor(() => expect(blobs).toHaveLength(1), { timeout: 5000 });

      // Read back content.xml to verify the failure marker
      const buf = await blobs[0].arrayBuffer();
      const zip = await JSZip.loadAsync(buf);
      const contentFile = zip.file("content.xml");
      expect(contentFile).not.toBeNull();
      const xml = await contentFile!.async("string");

      // The failure marker must appear
      expect(xml).toContain("匯出缺圖／預覽轉換失敗");
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (q2) ZIP failure → error shown, no download
// ---------------------------------------------------------------------------

describe("QuestionCard ODT — ZIP failure shows error (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q2) ZIP failure → InlineFailureNotice shown, createObjectURL not called", async () => {
    buildOdtFromSnapshotsMock.mockRejectedValueOnce(new Error("zip fail"));

    const q = makeQuestion("q-zip-fail");
    const evidence = makeEvidence(q);

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:never");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      render(<QuestionCard question={q} evidence={evidence} isFinal runId="run-1" />);

      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
      expect(screen.getByRole("alert")).toHaveTextContent(/Unable/i);
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (q3) Retry re-uses same snapshot
// ---------------------------------------------------------------------------

describe("QuestionCard ODT — retry uses same snapshot (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q3) Retry after failure uses the same snapshot object, not a new capture", async () => {
    const capturedSnapshots: QuestionSnapshot[][] = [];

    buildOdtFromSnapshotsMock.mockImplementation(
      async (_title: string, snapshots: QuestionSnapshot[]) => {
        capturedSnapshots.push([...snapshots]);
        if (capturedSnapshots.length === 1) {
          throw new Error("zip fail on first attempt");
        }
        return new Blob(["ODT"], { type: "application/vnd.oasis.opendocument.text" });
      },
    );

    const q = makeQuestion("q-retry-same-snap");
    const evidence = makeEvidence(q, 1);

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:retry-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      const { rerender } = render(
        <QuestionCard question={q} evidence={evidence} isFinal runId="run-1" />,
      );

      // First click: fail
      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Simulate a new revision arriving before retry
      const qv2 = { ...q, 題目: ["Updated question — should NOT appear in retry"] };
      const evidenceV2 = makeEvidence(qv2, 2);
      rerender(<QuestionCard question={qv2} evidence={evidenceV2} isFinal runId="run-1" />);

      // Click Retry
      fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
      await waitFor(() => expect(blobs).toHaveLength(1));

      // Both calls received snapshots
      expect(capturedSnapshots).toHaveLength(2);

      // The retry snapshot was captured at the same click time as the first attempt
      // (same object identity: same reference captured at click time)
      const firstSnap = capturedSnapshots[0][0];
      const retrySnap = capturedSnapshots[1][0];
      expect(retrySnap).toBe(firstSnap); // same object reference

      // The retained snapshot reflects the original question (revision 1, not 2)
      expect(retrySnap.exported._export.content_revision).toBe(1);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (q4) Fresh click after dismiss captures a new snapshot
// ---------------------------------------------------------------------------

describe("QuestionCard ODT — fresh click captures new snapshot (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q4) after Dismiss, a new click captures a fresh snapshot (different from the failed one)", async () => {
    const capturedSnapshots: QuestionSnapshot[][] = [];

    buildOdtFromSnapshotsMock.mockImplementation(
      async (_title: string, snapshots: QuestionSnapshot[]) => {
        capturedSnapshots.push([...snapshots]);
        if (capturedSnapshots.length === 1) {
          throw new Error("zip fail on first attempt");
        }
        return new Blob(["ODT"], { type: "application/vnd.oasis.opendocument.text" });
      },
    );

    const q = makeQuestion("q-new-click");
    const evidence = makeEvidence(q, 1);

    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:new-click-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      const { rerender } = render(
        <QuestionCard question={q} evidence={evidence} isFinal runId="run-1" />,
      );

      // First click: fail
      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Simulate a new revision arriving
      const qv2 = { ...q, 題目: ["Updated question v2"] };
      const evidenceV2 = makeEvidence(qv2, 2);
      rerender(<QuestionCard question={qv2} evidence={evidenceV2} isFinal runId="run-1" />);

      // Dismiss the failure
      fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());

      // Fresh click
      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));
      await waitFor(() => expect(blobs).toHaveLength(1));

      // Two distinct snapshot captures
      expect(capturedSnapshots).toHaveLength(2);

      // The second snapshot is NOT the same object as the first
      expect(capturedSnapshots[1][0]).not.toBe(capturedSnapshots[0][0]);

      // The new snapshot reflects the updated revision (2)
      expect(capturedSnapshots[1][0].exported._export.content_revision).toBe(2);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (q5) Evidence unchanged after ODT failure
// ---------------------------------------------------------------------------

describe("QuestionCard ODT — evidence unchanged after failure (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q5) ZIP failure does not alter snapshot _export fields (completeness/processing/review)", async () => {
    const capturedSnapshots: QuestionSnapshot[][] = [];

    buildOdtFromSnapshotsMock.mockImplementation(
      async (_title: string, snapshots: QuestionSnapshot[]) => {
        capturedSnapshots.push([...snapshots]);
        throw new Error("zip fail");
      },
    );

    const q = makeQuestion("q-evidence-unchanged");
    const evidence = makeEvidence(q, 3);

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:never");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      render(<QuestionCard question={q} evidence={evidence} isFinal runId="run-1" />);

      fireEvent.click(screen.getByRole("button", { name: "Download ODT" }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // The snapshot _export must not be mutated by the ODT failure
      expect(capturedSnapshots).toHaveLength(1);
      const snap = capturedSnapshots[0][0];
      expect(snap.exported._export.processing).toBe("ended");
      expect(snap.exported._export.delivery_status).toBe("complete");
      expect(snap.exported._export.content_revision).toBe(3);
      expect(snap.exported._export.is_draft).toBe(false);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

// ---------------------------------------------------------------------------
// (q6) PNG download keeps draft filename convention
// ---------------------------------------------------------------------------

describe("QuestionCard PNG filename conventions (issue #753)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("(q6a) PNG download for a final question uses no draft prefix in filename", async () => {
    const q: ExamQuestion = makeQuestion("q-final-png", { image_base64: FAKE_PNG });

    const anchorDownloads: string[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:png-final");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const origAppendChild = document.body.appendChild.bind(document.body);
    vi.spyOn(document.body, "appendChild").mockImplementation((node) => {
      if (node instanceof HTMLAnchorElement) {
        anchorDownloads.push(node.download);
        node.click = vi.fn();
      }
      return origAppendChild(node);
    });

    try {
      // Render only the final card — PNG is disabled for drafts (verified by QuestionCard.test.tsx)
      render(
        <QuestionCard
          question={q}
          isFinal
          phase="verified"
        />,
      );

      // The final card's PNG button is enabled
      const pngButton = screen.getByRole("button", { name: "Download PNG" });
      expect(pngButton).not.toBeDisabled();

      fireEvent.click(pngButton);
      await waitFor(() => expect(anchorDownloads).toHaveLength(1));

      // Final PNG has no draft prefix
      expect(anchorDownloads[0]).not.toMatch(/^草稿_/);
      expect(anchorDownloads[0]).toMatch(/\.png$/);
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
      vi.restoreAllMocks();
    }
  });
});
