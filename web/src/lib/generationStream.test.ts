import { describe, expect, it } from "vitest";
import type { LlmCallEvent } from "../hooks/useGenerate";
import { projectGenerationEvidence } from "./generationStream";

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
