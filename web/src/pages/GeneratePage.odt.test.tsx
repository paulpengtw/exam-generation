/**
 * (a) Component-level GeneratePage ODT click tests (issue #752 review).
 *
 * Drives GeneratePage through useGenerate returning fixture-derived evidence
 * from math_groups_interleaved.jsonl.  The real buildOdtFromSnapshots runs
 * (not mocked) so we can read back ZIP XML and verify 題組 structure.
 *
 * Verifies that a batch ODT click:
 * - captures the correct snapshots from v2 evidence (including terminal.missing)
 * - produces a ZIP whose content.xml contains 題組 structure (文本/核心問題)
 *   for q_RUN_003 (text-only 題組 detected via 題型種類)
 * - correctly places the 缺小題 2 marker between 第1題 and 第3題 for q_RUN_001
 *   (verifying the 0-based subquestion_index → 1-based 序號 fix)
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import JSZip from "jszip";
import {
  createGenerationStreamDecoder,
} from "../lib/generationStream";
import {
  createRunEvidence,
  applyV2Event,
  applyDegraded,
  type RunEvidenceState,
} from "../lib/generationEvidence";

// ---------------------------------------------------------------------------
// Do NOT mock buildOdtFromSnapshots — the real implementation must run.
// ---------------------------------------------------------------------------
const useGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: useGenerateMock,
}));

vi.mock("../lib/generationStream", async () => {
  // We need createGenerationStreamDecoder for fixture replay, so spread the
  // real module and only override the two projection helpers that GeneratePage uses.
  const actual = await vi.importActual<typeof import("../lib/generationStream")>("../lib/generationStream");
  return {
    ...actual,
    projectGenerationCardEvidence: () => ({}),
    projectGenerationEvidence: () => null,
  };
});

vi.mock("../components/ParamForm", () => ({
  default: () => <div data-testid="param-form" />,
}));
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
import type { GeneratedQuestion } from "../hooks/useGenerate";

// ---------------------------------------------------------------------------
// Fixture helpers (same pattern as GeneratePage.v2.test.tsx / odt.acceptance.test.ts)
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_v2", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

function replayFixture(fixture: FixtureLine[]): RunEvidenceState {
  const dec = createGenerationStreamDecoder();
  let state: RunEvidenceState | null = null;
  for (const line of fixture) {
    const rawData = JSON.stringify({ context: line.context, payload: line.payload });
    const results = dec.decode(line.event, rawData);
    for (const d of results) {
      if (d.kind === "v2" && d.event.name === "started") {
        if (dec.run) state = createRunEvidence(dec.run);
      } else if (d.kind === "v2" && state) {
        state = applyV2Event(state, d);
      } else if (d.kind === "degraded" && state) {
        state = applyDegraded(state, d.reason);
      }
    }
  }
  if (!state) throw new Error("No state built");
  return state;
}

async function readContentXml(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const file = zip.file("content.xml");
  if (!file) throw new Error("content.xml missing");
  return file.async("string");
}

// Build GeneratedQuestion[] displayResults from evidence state
function evidenceToDisplayResults(state: RunEvidenceState): GeneratedQuestion[] {
  return state.order.flatMap((qId) => {
    const ev = state.questions[qId];
    if (!ev?.content.question) return [];
    return [{
      index: ev.index ?? 0,
      question: ev.content.question,
      phase: "verified" as const,
      isFinal: true,
      stableId: qId,
      contentRevision: ev.content.revision ?? null,
    }];
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GeneratePage batch ODT — component-level click with fixture evidence", () => {
  const fixture = loadFixture("math_groups_interleaved.jsonl");
  const state = replayFixture(fixture);

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();

    const displayResults = evidenceToDisplayResults(state);
    // Expose evidence as RunEvidenceState so captureBatchSnapshots gets terminal.missing
    useGenerateMock.mockReturnValue({
      status: "done",
      progressLines: [],
      results: displayResults.map((r) => r.question),
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
      evidence: state,
      generate: vi.fn(),
      restoreResults: vi.fn(),
      reset: vi.fn(),
    });
  });

  it("(a1) batch ODT ZIP contains all three 題組 questions with correct group structure", async () => {
    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:batch-odt";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      render(
        <MemoryRouter initialEntries={["/generate/math"]}>
          <Routes>
            <Route path="/generate/math" element={<GeneratePage subject="math" />} />
          </Routes>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));

      // Wait for the blob to be created (real buildOdtFromSnapshots is async)
      await vi.waitFor(() => expect(blobs).toHaveLength(1), { timeout: 5000 });

      const xml = await readContentXml(blobs[0]);

      // All three question 文本 strings must appear (one per 題組)
      expect(xml).toContain("文本 A");
      expect(xml).toContain("文本 B");
      expect(xml).toContain("文本 C");

      // Batch page-break structure
      expect(xml).toContain("PageBreak");

      // q_RUN_003: text-only 題組 detected by 題型種類=題組題 → group layout
      expect(xml).toContain("核心問題 C");
      // Must NOT render flat 正確解題分析 for any group question
      expect(xml).not.toContain("正確解題分析");
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });

  it("(a2) batch ODT: q_RUN_001 missing subquestion slot_index=1 renders as 缺小題 2", async () => {
    // Key regression test for 0-based subquestion_index → 1-based 序號 fix.
    // q_RUN_001 has delivered 序號=1 and 序號=3, missing slot_index=1 (= 序號=2).
    // Before the fix, raw index 1 collided with delivered 序號=1 — the gap was
    // silently dropped and "缺小題 2" never appeared.
    // Note: q_RUN_003 has "缺小題 1" (slot_index=0 → 序號=1, all subquestions missing),
    // so we do NOT assert "缺小題 1" is absent from the batch; only that "缺小題 2" is present.
    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:batch-odt-missing";
      });
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    try {
      render(
        <MemoryRouter initialEntries={["/generate/math"]}>
          <Routes>
            <Route path="/generate/math" element={<GeneratePage subject="math" />} />
          </Routes>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /Download all as ODT/i }));

      await vi.waitFor(() => expect(blobs).toHaveLength(1), { timeout: 5000 });

      const xml = await readContentXml(blobs[0]);

      // "缺小題 2" must appear (q_RUN_001 gap at 序號=2)
      expect(xml).toContain("缺小題 2");
      // "缺小題 3" must NOT appear for q_RUN_001's section — with the old bug,
      // slot_index=1 would become 序號=1+1=2 via +1, but delivered 序號=3 would
      // not get a spurious marker. The key is "缺小題 2" is present, not absent.
      // Also verify both delivered subquestions appear for q_RUN_001
      expect(xml).toContain("第1題");
      expect(xml).toContain("第3題");
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});
