import { describe, expect, it } from "vitest";
import type { ExamQuestion } from "../../../hooks/useGenerate";
import type { ResultsWorkspaceLive } from "./resultsWorkspace";
import { exportResultsWorkspace, importResultsWorkspace } from "./resultsWorkspace";

const question: ExamQuestion = {
  id: "q-1", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["q-1"], 正確解題分析: ["analysis"],
};

const live: ResultsWorkspaceLive = {
  results: [question],
  displayResults: [{ index: 0, question, phase: "verified", isFinal: true, trail: [{
    code: "verification_trail", kind: "initial", question_id: "q-1",
    timestamp: "2026-01-01T00:00:00+00:00", snapshot: { id: "q-1", 題目: ["before"] },
  }] }],
  progressLines: ["Question 1 complete"], errorMessage: null,
  startedAt: 1000, finishedAt: 2000, subQuestionTotal: 3,
  requestedTotal: 2, submittedSubQuestionCount: 3, status: "idle",
};

describe("results workspace adapter", () => {
  it("round-trips received questions, display lanes, progress and totals", () => {
    const snapshot = exportResultsWorkspace(live);
    expect(snapshot).toEqual({
      kind: "results", version: 1, results: live.results, displayResults: live.displayResults,
      progressLines: ["Question 1 complete"], errorMessage: null, startedAt: 1000,
      finishedAt: 2000, subQuestionTotal: 3, requestedTotal: 2, submittedSubQuestionCount: 3,
      completion: "settled",
    });
    expect(importResultsWorkspace(JSON.parse(JSON.stringify(snapshot)))).toEqual(snapshot);
  });

  it.each([
    { status: "idle", finishedAt: 2000, completion: "settled" },
    { status: "idle", finishedAt: 0, completion: "settled" },
    { status: "idle", finishedAt: null, completion: "unknown" },
    { status: "generating", finishedAt: null, completion: "unknown" },
    { status: "generating", finishedAt: 2000, completion: "unknown" },
    { status: "error", finishedAt: null, completion: "error" },
    { status: "error", finishedAt: 2000, completion: "error" },
  ] as const)("maps $status / finishedAt=$finishedAt to $completion", ({ status, finishedAt, completion }) => {
    const snapshot = exportResultsWorkspace({ ...live, status, finishedAt });
    expect(snapshot.completion).toBe(completion);
    expect(importResultsWorkspace(snapshot)?.completion).toBe(completion);
  });

  it("accepts empty results, null timing/counts and an error message", () => {
    const snapshot = exportResultsWorkspace({ ...live, results: [], displayResults: [], progressLines: [],
      errorMessage: "Request failed", startedAt: null, finishedAt: null, subQuestionTotal: null,
      requestedTotal: 0, submittedSubQuestionCount: null, status: "error" });
    expect(importResultsWorkspace(snapshot)).toEqual(snapshot);
  });

  it("excludes provider diagnostics and live status from exported and imported state", () => {
    const withDiagnostics = { ...live, llmCalls: [{ type: "request", messages: ["provider payload"] }] };
    const snapshot = exportResultsWorkspace(withDiagnostics);
    expect(snapshot).not.toHaveProperty("llmCalls");
    expect(snapshot).not.toHaveProperty("status");
    expect(importResultsWorkspace({ ...snapshot, llmCalls: withDiagnostics.llmCalls, status: "generating" })).toEqual(snapshot);
  });

  it.each([null, 42, "results", [], {}])("rejects a malformed envelope %#", (raw) => {
    expect(importResultsWorkspace(raw)).toBeNull();
  });

  it.each([
    { kind: "form" }, { version: 2 }, { version: "1" },
    { results: {} }, { results: [null] }, { results: [[]] },
    { displayResults: {} }, { displayResults: [null] }, { displayResults: [[]] },
    { displayResults: [{ ...live.displayResults[0], index: 0.5 }] },
    { displayResults: [{ ...live.displayResults[0], index: "0" }] },
    { displayResults: [{ ...live.displayResults[0], question: null }] },
    { displayResults: [{ ...live.displayResults[0], question: [] }] },
    { displayResults: [{ ...live.displayResults[0], isFinal: "true" }] },
    { progressLines: [42] }, { errorMessage: 42 },
    { startedAt: Number.NaN }, { finishedAt: Number.POSITIVE_INFINITY },
    { subQuestionTotal: "3" }, { requestedTotal: null }, { requestedTotal: Number.NaN },
    { submittedSubQuestionCount: Number.NEGATIVE_INFINITY }, { completion: "completed" },
  ])("rejects invalid results fields %#", (patch) => {
    expect(importResultsWorkspace({ ...exportResultsWorkspace(live), ...patch })).toBeNull();
  });
});
