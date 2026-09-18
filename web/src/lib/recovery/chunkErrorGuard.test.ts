/**
 * Chunk error guard — unit tests.
 * Issue #777.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { classifyChunkError, decideOnChunkError } from "./chunkErrorGuard";
import type { AutoRefreshEligibility } from "./autoRefresh";

beforeEach(() => {
  try { sessionStorage.clear(); } catch { /* ignore */ }
});

const ELIGIBLE: AutoRefreshEligibility = { eligible: true };
const INELIGIBLE: AutoRefreshEligibility = { eligible: false, reason: "not_safe" };

describe("classifyChunkError", () => {
  it("unit: returns chunk_load_error for ChunkLoadError name", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    expect(classifyChunkError(err)).toBe("chunk_load_error");
  });

  it("unit: returns chunk_load_error for dynamically imported module message", () => {
    const err = new Error("Failed to fetch dynamically imported module: /assets/foo.js");
    expect(classifyChunkError(err)).toBe("chunk_load_error");
  });

  it("unit: returns preload_error for Unable to preload message", () => {
    const err = new Error("Unable to preload CSS for /assets/foo.css");
    expect(classifyChunkError(err)).toBe("preload_error");
  });

  it("unit: returns null for unrelated errors", () => {
    expect(classifyChunkError(new Error("Network error"))).toBeNull();
    expect(classifyChunkError(null)).toBeNull();
    expect(classifyChunkError("string error")).toBeNull();
  });
});

describe("decideOnChunkError", () => {
  it("unit: old HTML stops reload loop", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-OLD",
      releasedBuildId: "build-NEW",
      autoRefreshEligibility: ELIGIBLE,
    });
    expect(result.action).toBe("show_error");
    expect(result.kind).toBe("old_html");
  });

  it("unit: eligible empty page triggers reload decision", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-A",
      releasedBuildId: "build-A",
      autoRefreshEligibility: ELIGIBLE,
    });
    expect(result.action).toBe("reload");
    expect(result.kind).toBe("chunk_load_error");
  });

  it("unit: ineligible page (not_safe) returns show_error", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-A",
      releasedBuildId: null,
      autoRefreshEligibility: INELIGIBLE,
    });
    expect(result.action).toBe("show_error");
    expect(result.reason).toBe("not_safe");
  });

  it("unit: preload error on eligible page triggers reload", () => {
    const err = new Error("Unable to preload CSS for /assets/foo.css");
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-A",
      releasedBuildId: "build-A",
      autoRefreshEligibility: ELIGIBLE,
    });
    expect(result.action).toBe("reload");
    expect(result.kind).toBe("preload_error");
  });

  it("unit: non-chunk error returns show_error", () => {
    const err = new Error("Network error");
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-A",
      releasedBuildId: "build-A",
      autoRefreshEligibility: ELIGIBLE,
    });
    expect(result.action).toBe("show_error");
    expect(result.reason).toBe("not_a_chunk_error");
  });
});
