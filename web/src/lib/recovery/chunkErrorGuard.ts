/**
 * Chunk-load and preload error guard — issue #777.
 *
 * Routes Vite/Rollup chunk-load and preload errors through the same
 * auto-refresh safety decision. An error alone never authorizes destructive
 * navigation.
 *
 * Old-HTML detection: if the running build ID differs from the released build
 * ID, a reload would loop (the same stale HTML would be served again). Stop
 * the loop and show an error notice instead.
 */
import type { AutoRefreshEligibility } from "./autoRefresh";

export type ChunkErrorKind = "chunk_load_error" | "preload_error" | "old_html";

export interface ChunkErrorDecision {
  action: "reload" | "show_error";
  kind: ChunkErrorKind;
  reason?: string;
}

/**
 * Returns the kind of chunk/preload error, or null if the error is unrelated.
 */
export function classifyChunkError(error: unknown): ChunkErrorKind | null {
  if (!error || typeof error !== "object") return null;
  const e = error as { name?: string; message?: string };
  if (e.name === "ChunkLoadError") return "chunk_load_error";
  if (typeof e.message === "string") {
    if (
      e.message.includes("Failed to fetch dynamically imported module") ||
      e.message.includes("Importing a module script failed")
    ) {
      return "chunk_load_error";
    }
    if (
      e.message.includes("Unable to preload CSS") ||
      e.message.includes("Unable to preload")
    ) {
      return "preload_error";
    }
  }
  return null;
}

export function decideOnChunkError(params: {
  error: unknown;
  currentBuildId: string;
  releasedBuildId: string | null;
  autoRefreshEligibility: AutoRefreshEligibility;
}): ChunkErrorDecision {
  const { error, currentBuildId, releasedBuildId, autoRefreshEligibility } = params;

  const kind = classifyChunkError(error);
  if (kind === null) {
    return { action: "show_error", kind: "chunk_load_error", reason: "not_a_chunk_error" };
  }

  // Old-HTML detection: if we know the released build and it differs from
  // what is running, reloading would serve the same stale HTML again.
  if (releasedBuildId !== null && currentBuildId !== releasedBuildId) {
    return { action: "show_error", kind: "old_html", reason: "old_html" };
  }

  if (!autoRefreshEligibility.eligible) {
    return {
      action: "show_error",
      kind,
      reason: autoRefreshEligibility.reason,
    };
  }

  return { action: "reload", kind };
}
