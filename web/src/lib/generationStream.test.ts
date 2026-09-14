import { describe, expect, it } from "vitest";
import type { GeneratedQuestion, LlmCallEvent } from "../hooks/useGenerate";
import { projectGenerationCardEvidence, projectGenerationEvidence } from "./generationStream";

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
