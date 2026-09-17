import { describe, expect, it } from "vitest";
import type { ModificationStageEvent } from "../hooks/useModificationRun";
import { decodeModificationEvent, projectModificationEvidence } from "./modificationStream";

describe("projectModificationEvidence", () => {
  it("tags the same modification steps without generation identity or manifest fields", () => {
    const steps: readonly ModificationStageEvent[] = [
      { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "start", ts: 1 },
      { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "end", ts: 2 },
    ];

    const evidence = projectModificationEvidence(steps);

    expect(evidence).toEqual({ profile: "modification", steps });
    expect(evidence.steps).toBe(steps);
    expect(Object.keys(evidence)).toEqual(["profile", "steps"]);
  });
});

describe("decodeModificationEvent", () => {
  const question = {
    id: "q1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
    題目: ["question"], 正確解題分析: ["answer"],
  };

  it("decodes a valid stage with optional retry and message", () => {
    expect(decodeModificationEvent("stage", JSON.stringify({
      agent: "corrector", stage: "correct", step: "修正", status: "start", ts: 3,
      retry: 1, message: "retrying",
    }))).toEqual({
      kind: "stage",
      event: {
        type: "stage", agent: "corrector", stage: "correct", step: "修正", status: "start", ts: 3,
        retry: 1, message: "retrying",
      },
    });
  });

  it("rejects a stage with an invalid status", () => {
    expect(decodeModificationEvent("stage", JSON.stringify({
      agent: "modifier", stage: "modification", step: "modify", status: "done", ts: 1,
    }))).toBeNull();
  });

  it("rejects a non-JSON stage", () => {
    expect(decodeModificationEvent("stage", "not JSON")).toBeNull();
  });

  it("decodes a result and filters non-string ripple paths", () => {
    expect(decodeModificationEvent("result", JSON.stringify({
      record_id: "record-2", question, ripple_report: ["文本", null, 1, {}, "題目"],
      verified: true, verification: { passed: true }, failure_details: "details",
    }))).toEqual({
      kind: "result",
      result: {
        record_id: "record-2", question, ripple_report: ["文本", "題目"],
        verified: true, verification: { passed: true }, failure_details: "details",
      },
    });
  });

  it.each([null, "question", undefined])("rejects a result whose question is %s", (question) => {
    expect(decodeModificationEvent("result", JSON.stringify({ question }))).toBeNull();
  });

  it("extracts the message from a JSON error object", () => {
    expect(decodeModificationEvent("error", '{"message":"connection lost"}')).toEqual({
      kind: "error", error: new Error("connection lost"),
    });
  });

  it("uses raw error text when no message object is available", () => {
    expect(decodeModificationEvent("error", "connection lost")).toEqual({
      kind: "error", error: new Error("connection lost"),
    });
    expect(decodeModificationEvent("error", '{"message":""}')).toEqual({
      kind: "error", error: new Error('{"message":""}'),
    });
  });

  it("uses the existing fallback for empty error data", () => {
    expect(decodeModificationEvent("error", "")).toEqual({
      kind: "error", error: new Error("Modification stream failed"),
    });
  });

  it("decodes a done payload with the existing result defaults", () => {
    expect(decodeModificationEvent("done", JSON.stringify({ question }))).toEqual({
      kind: "done",
      result: {
        record_id: null, question, ripple_report: [], verified: false,
        verification: null, failure_details: null,
      },
    });
  });

  it("decodes done without a payload as a null result", () => {
    expect(decodeModificationEvent("done", "")).toEqual({ kind: "done", result: null });
  });

  it("ignores unknown event names", () => {
    expect(decodeModificationEvent("unknown", JSON.stringify({ question }))).toBeNull();
  });
});
