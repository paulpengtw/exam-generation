import { describe, expect, it } from "vitest";
// The buildQueryString helper is currently module-private. This test file
// intentionally imports it via a named re-export added in the implementation
// step below.
import { buildQueryString, parseErrorEventData } from "./useGenerate";

describe("useGenerate — model overrides", () => {
  it("does not emit model_plan / model_execute when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });

  it("emits model_plan / model_execute when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "claude-opus-4-6",
      model_execute: "claude-haiku-4-6",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("model_plan")).toBe("claude-opus-4-6");
    expect(params.get("model_execute")).toBe("claude-haiku-4-6");
  });

  it("does not emit model_plan / model_execute when set to empty string", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "",
      model_execute: "",
    });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });
});

describe("useGenerate — parseErrorEventData", () => {
  it("returns .message from a valid structured JSON payload", () => {
    const raw = JSON.stringify({ code: "generation_failed", message: "Question generation failed (RuntimeError)" });
    expect(parseErrorEventData(raw)).toBe("Question generation failed (RuntimeError)");
  });

  it("returns .message from a stream_failed payload", () => {
    const raw = JSON.stringify({ code: "stream_failed", message: "Stream error (ValueError)" });
    expect(parseErrorEventData(raw)).toBe("Stream error (ValueError)");
  });

  it("falls back to the raw string when the payload is not valid JSON", () => {
    expect(parseErrorEventData("something went wrong")).toBe("something went wrong");
  });

  it("falls back to the raw string when JSON lacks a message field", () => {
    const raw = JSON.stringify({ code: "generation_failed" });
    expect(parseErrorEventData(raw)).toBe(raw);
  });

  it("falls back to 'Unknown error' when the raw string is empty", () => {
    expect(parseErrorEventData("")).toBe("Unknown error");
  });

  it("falls back to the raw string for a plain string payload", () => {
    expect(parseErrorEventData("plain error text")).toBe("plain error text");
  });
});
