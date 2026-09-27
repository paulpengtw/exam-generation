import { describe, expect, it } from "vitest";
import type { GeneratedQuestion, LlmCallEvent } from "../hooks/useGenerate";
import { projectGenerationCardEvidence, projectGenerationEvidence, createGenerationStreamDecoder } from "./generationStream";

describe("projectGenerationEvidence", () => {
  it("keeps only stage events in stream order and carries the subquestion count", () => {
    const calls: readonly LlmCallEvent[] = [
      { type: "request", purpose: "generate", agent: "generator", model: "model", messages: [] },
      { type: "stage", agent: "generator", stage: "llm_generate", status: "start", ts: 2 },
      { type: "thinking", purpose: "generate", agent: "generator", text: "thinking" },
      { type: "content", purpose: "generate", agent: "generator", text: "content" },
      { type: "stage", agent: "generator", stage: "llm_generate", status: "end", ts: 1 },
      { type: "response", purpose: "generate", agent: "generator", model: "model" },
      { type: "stage", agent: "sub_generator#1", stage: "llm_generate", status: "start", ts: 3 },
    ];

    expect(projectGenerationEvidence(calls, 3)).toEqual({
      profile: "generate-legacy",
      stageEvents: [
        { type: "stage", agent: "generator", stage: "llm_generate", status: "start", ts: 2 },
        { type: "stage", agent: "generator", stage: "llm_generate", status: "end", ts: 1 },
        { type: "stage", agent: "sub_generator#1", stage: "llm_generate", status: "start", ts: 3 },
      ],
      subQuestionCount: 3,
    });
  });

  it("projects an empty stream without inventing stages or a count", () => {
    expect(projectGenerationEvidence([], null)).toEqual({
      profile: "generate-legacy",
      stageEvents: [],
      subQuestionCount: null,
    });
  });
});

describe("projectGenerationCardEvidence", () => {
  it("projects only the five card fields and defaults an absent figure policy trail", () => {
    const item: GeneratedQuestion = {
      index: 1,
      question: { 情境: ["公共"], 題型種類: "單一題", 題型: "選擇題", 題目: ["question"], 正確解題分析: ["answer"] },
      phase: "image",
      isFinal: false,
      trail: [{ code: "verification_trail", kind: "initial", question_id: "q1", timestamp: "2026-09-15T00:00:00Z", snapshot: { 題目: ["question"] } }],
      referenceExampleRecord: {
        entries: [{ code: "reference_example", kind: "example", question_id: "q1", stage: "generate", source: "example.json", timestamp: "2026-09-15T00:00:00Z" }],
      },
    };

    const evidence = projectGenerationCardEvidence(item);

    expect(evidence).toEqual({
      phase: "image",
      isFinal: false,
      trail: [{ code: "verification_trail", kind: "initial", question_id: "q1", timestamp: "2026-09-15T00:00:00Z", snapshot: { 題目: ["question"] } }],
      figurePolicyTrail: [],
      referenceExampleRecord: {
        entries: [{ code: "reference_example", kind: "example", question_id: "q1", stage: "generate", source: "example.json", timestamp: "2026-09-15T00:00:00Z" }],
      },
    });
    expect(evidence.trail).toBe(item.trail);
    expect(Object.keys(evidence)).toEqual([
      "phase", "isFinal", "trail", "figurePolicyTrail", "referenceExampleRecord",
    ]);
  });
});

// ---------------------------------------------------------------------------
// F1: createGenerationStreamDecoder
// ---------------------------------------------------------------------------

describe("createGenerationStreamDecoder", () => {
  const validManifest = {
    protocol_version: 2,
    total: 2,
    questions: [
      { index: 0, question_id: "q_RUN_001" },
      { index: 1, question_id: "q_RUN_002" },
    ],
    generation_log_id: null,
  };
  const validContext = { run_id: "RUN", event_seq: 1 };
  const validStartedData = JSON.stringify({ context: validContext, payload: validManifest });

  it("starts in awaiting-start mode with null run", () => {
    const dec = createGenerationStreamDecoder();
    expect(dec.mode).toBe("awaiting-start");
    expect(dec.run).toBeNull();
  });

  it("transitions to v2 on a valid manifest and sets run", () => {
    const dec = createGenerationStreamDecoder();
    const events = dec.decode("started", validStartedData);
    expect(dec.mode).toBe("v2");
    expect(dec.run).toEqual({
      runId: "RUN",
      total: 2,
      manifest: [
        { index: 0, questionId: "q_RUN_001" },
        { index: 1, questionId: "q_RUN_002" },
      ],
    });
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: "v2", event: { name: "started" } });
  });

  it("is unsupported with unknown_protocol when protocol_version is not 2", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({
      context: validContext,
      payload: { protocol_version: 3, total: 1, questions: [{ index: 0, question_id: "q1" }] },
    });
    const events = dec.decode("started", data);
    expect(dec.mode).toBe("unsupported");
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "unknown_protocol" });
  });

  it("is unsupported with invalid_manifest on duplicate question_id", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({
      context: validContext,
      payload: {
        protocol_version: 2,
        total: 2,
        questions: [
          { index: 0, question_id: "same_id" },
          { index: 1, question_id: "same_id" },
        ],
      },
    });
    const events = dec.decode("started", data);
    expect(dec.mode).toBe("unsupported");
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "invalid_manifest" });
  });

  it("is unsupported with invalid_manifest on index gap", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({
      context: validContext,
      payload: {
        protocol_version: 2,
        total: 2,
        questions: [
          { index: 0, question_id: "q1" },
          { index: 2, question_id: "q2" }, // gap: index 2 instead of 1
        ],
      },
    });
    const events = dec.decode("started", data);
    expect(dec.mode).toBe("unsupported");
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "invalid_manifest" });
  });

  it("is unsupported with invalid_manifest when total does not match questions length", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({
      context: validContext,
      payload: {
        protocol_version: 2,
        total: 3, // mismatch
        questions: [
          { index: 0, question_id: "q1" },
          { index: 1, question_id: "q2" },
        ],
      },
    });
    const events = dec.decode("started", data);
    expect(dec.mode).toBe("unsupported");
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "invalid_manifest" });
  });

  it("transitions to legacy on a started event with generation_log_id (no context)", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({ generation_log_id: "LOG123" });
    const events = dec.decode("started", data);
    expect(dec.mode).toBe("legacy");
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ kind: "legacy", name: "started", data });
  });

  it("transitions to legacy on an empty started payload", () => {
    const dec = createGenerationStreamDecoder();
    const events = dec.decode("started", "{}");
    expect(dec.mode).toBe("legacy");
    expect(events[0]).toMatchObject({ kind: "legacy", name: "started" });
  });

  it("holds events before started and returns {kind:'held'}", () => {
    const dec = createGenerationStreamDecoder();
    const ev = dec.decode("stage", JSON.stringify({ type: "stage" }));
    expect(dec.mode).toBe("awaiting-start");
    expect(ev).toHaveLength(1);
    expect(ev[0]).toEqual({ kind: "held" });
  });

  it("replays held events after a valid started", () => {
    const dec = createGenerationStreamDecoder();
    const stageData = JSON.stringify({ context: { run_id: "RUN", event_seq: 2 }, payload: { type: "stage" } });
    dec.decode("stage", stageData); // held
    const events = dec.decode("started", validStartedData);
    // started + replayed stage
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ kind: "v2", event: { name: "started" } });
    expect(events[1]).toMatchObject({ kind: "v2", event: { name: "stage" } });
  });

  it("ignores events with wrong run_id in v2 mode", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);
    const data = JSON.stringify({ context: { run_id: "OTHER", event_seq: 2 }, payload: {} });
    const events = dec.decode("result", data);
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ kind: "ignore", reason: "wrong_run" });
  });

  it("ignores events without integer event_seq in v2 mode", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);
    const data = JSON.stringify({ context: { run_id: "RUN", event_seq: "notanumber" }, payload: {} });
    const events = dec.decode("result", data);
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ kind: "ignore", reason: "invalid_envelope" });
  });

  it("returns missing_started when done with v2 context arrives before started", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({ context: { run_id: "RUN", event_seq: 5 }, payload: {} });
    const events = dec.decode("done", data);
    expect(dec.mode).toBe("unsupported");
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "missing_started" });
  });

  it("returns missing_started when error with v2 context arrives before started", () => {
    const dec = createGenerationStreamDecoder();
    const data = JSON.stringify({ context: { run_id: "RUN", event_seq: 5 }, payload: {} });
    const events = dec.decode("error", data);
    expect(dec.mode).toBe("unsupported");
    expect(events[0]).toEqual({ kind: "mode", mode: "unsupported", reason: "missing_started" });
  });

  it("falls through to legacy when done with no v2 context arrives before started", () => {
    const dec = createGenerationStreamDecoder();
    const events = dec.decode("done", "{}");
    expect(dec.mode).toBe("legacy");
    expect(events[0]).toEqual({ kind: "legacy", name: "done", data: "{}" });
  });

  it("passes all events through in legacy mode", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", "{}"); // → legacy
    const data = JSON.stringify({ something: "legacy_result" });
    const events = dec.decode("result", data);
    expect(events[0]).toEqual({ kind: "legacy", name: "result", data });
  });

  it("decodes v2 events with correct structure after valid started", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);
    const ctx = { run_id: "RUN", event_seq: 2, question_id: "q_RUN_001", index: 0, content_revision: 1 };
    const payload = { index: 0, phase: "draft", question: { id: "q_RUN_001" } };
    const data = JSON.stringify({ context: ctx, payload });
    const events = dec.decode("question_update", data);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      kind: "v2",
      event: {
        name: "question_update",
        context: ctx,
        payload,
      },
    });
  });
});
