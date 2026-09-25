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

  it("records an interrupted run separately from unknown terminal evidence", () => {
    const snapshot = exportResultsWorkspace({ ...live, status: "error", terminalEvidence: false });

    expect(snapshot.completion).toBe("error");
    expect(snapshot.processing).toBe("interrupted");
    expect(snapshot.evidence?.[0]).toMatchObject({ processing: "interrupted", terminal: "unknown" });
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

  it("strips nested provider payloads and refuses object URLs before storage", () => {
    const unsafeQuestion = {
      ...question,
      provider_payload: { api_key: "secret" },
      metadata: { diagnostics: { raw_response: "secret" }, visible: "keep" },
    };
    const safe = exportResultsWorkspace({
      ...live,
      results: [unsafeQuestion],
      displayResults: [{ ...live.displayResults[0], question: unsafeQuestion }],
    });
    expect(safe.results[0]).not.toHaveProperty("provider_payload");
    expect(safe.results[0].metadata).toEqual({ visible: "keep" });

    expect(() => exportResultsWorkspace({
      ...live,
      results: [{ ...question, image_base64: "blob:http://expired" }],
    })).toThrow(/object URLs/);
  });

  it("preserves mixed final and displayed partial content with durable image evidence", () => {
    const partial = {
      ...question,
      id: "q-partial",
      題目: ["partial question"],
      image_base64: "cGFydGlhbC1wbmc=",
    };
    const richLive = {
      ...live,
      results: [{ ...question, image_base64: "ZmluYWwtcG5n" }],
      displayResults: [
        Object.assign(live.displayResults[0], {
          stableId: "q-1",
          contentRevision: 4,
        }),
        { index: 1, question: partial, phase: "draft" as const, isFinal: false, stableId: "q-partial", contentRevision: null },
      ],
      terminalEvidence: false,
      runId: "run-1",
    };

    const snapshot = exportResultsWorkspace(richLive);

    expect(snapshot.processing).toBe("unknown");
    expect(snapshot.terminalEvidence).toBe(false);
    expect(snapshot.runId).toBe("run-1");
    expect(snapshot.evidence).toEqual([
      expect.objectContaining({ stableId: "q-1", contentRevision: 4, receipt: "final", processing: "unknown" }),
      expect.objectContaining({ stableId: "q-partial", contentRevision: null, receipt: "draft", processing: "unknown" }),
    ]);
    expect(snapshot.images).toEqual({
      "q-1": { base64: "ZmluYWwtcG5n", mimeType: "image/png", location: "question" },
      "q-partial": { base64: "cGFydGlhbC1wbmc=", mimeType: "image/png", location: "question" },
    });
    expect(snapshot).not.toHaveProperty("llmCalls");
  });

  it("keeps final subquestion image bytes when a displayed draft has the same stable ID", () => {
    const finalQuestion = {
      ...question,
      subquestions: [{ 序號: 1, 題目: ["final"], image_base64: "ZmluYWwtc3Vi" }],
    };
    const draftQuestion = {
      ...finalQuestion,
      subquestions: [{ 序號: 1, 題目: ["draft"], image_base64: "ZHJhZnQtc3Vi" }],
    };
    const snapshot = exportResultsWorkspace({
      ...live,
      results: [finalQuestion],
      displayResults: [{ ...live.displayResults[0], question: draftQuestion, stableId: "q-1", isFinal: false }],
      terminalEvidence: false,
    });

    expect(snapshot.images?.["q-1::subquestion::1"]?.base64).toBe("ZmluYWwtc3Vi");
  });

  it("rehydrates durable image bytes and rejects object URLs", () => {
    const snapshot = exportResultsWorkspace(live);
    const imported = importResultsWorkspace({
      ...snapshot,
      displayResults: [{
        ...snapshot.displayResults[0],
        question: { ...snapshot.displayResults[0].question, image_base64: undefined },
      }],
      images: {
        "q-1": { base64: "cG5n", mimeType: "image/png", location: "question" },
      },
    });

    expect(imported?.displayResults[0].question.image_base64).toBe("cG5n");
    expect(importResultsWorkspace({
      ...snapshot,
      images: { "q-1": { base64: "blob:http://example/expired", mimeType: "image/png", location: "question" } },
    })).toBeNull();
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
