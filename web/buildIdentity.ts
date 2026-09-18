/**
 * Build identity helpers — used by vite.config.ts at build time.
 *
 * computeBuildId: deterministic sha256 over commit + public VITE_* config.
 * buildIdentityPlugin: Vite plugin that defines __BUILD_ID__ / __BUILD_ENVIRONMENT__
 *   and emits dist/build-meta.json + dist/release/policy.json.
 *
 * Issue #770: release version detection.
 */
import { createHash, randomUUID } from "node:crypto";
import { execSync } from "node:child_process";
import type { Plugin } from "vite";

// Commit values that are not real identifiers.
const PLACEHOLDER_COMMITS = new Set(["unknown", "dev", "local", "HEAD"]);

// Stable per-process dev id — computed once at module load, same within a run.
const DEV_PROCESS_ID = "dev-" + randomUUID().replace(/-/g, "").slice(0, 16);

// Public VITE_* keys whose values affect the bundle content.
const BUNDLE_CONFIG_KEYS = [
  "VITE_ENVIRONMENT",
  "VITE_IS_STAGING",
  "VITE_SENTRY_DSN",
  "VITE_SENTRY_RELEASE",
] as const;

/**
 * Resolve the commit SHA from common CI/hosting environment variables,
 * falling back to `git rev-parse HEAD` if available.
 */
export function resolveCommitSha(): string {
  const fromEnv =
    process.env.RAILWAY_GIT_COMMIT_SHA ||
    process.env.RENDER_GIT_COMMIT ||
    process.env.GIT_COMMIT_SHA;
  if (fromEnv) return fromEnv;
  try {
    return execSync("git rev-parse HEAD", {
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    return "unknown";
  }
}

export interface BuildIdOptions {
  /** Commit SHA (from resolveCommitSha or an explicit override). */
  commit: string;
  /** Public VITE_* environment variables that affect the bundle. */
  publicConfig: Record<string, string | undefined>;
  /** Vite mode ('production' | 'development' | …). */
  mode: string;
}

/**
 * Compute a deterministic build ID.
 *
 * - Non-production mode: returns a stable per-process `dev-…` string.
 * - Production mode: sha256 hex (64 chars) over `commit + canonical-config-json`.
 *   If `process.env.BUILD_ID` is set it is returned verbatim (after the same
 *   placeholder check).  A placeholder commit or BUILD_ID throws with a clear
 *   message naming the fix.
 */
export function computeBuildId({ commit, publicConfig, mode }: BuildIdOptions): string {
  if (mode !== "production") {
    return DEV_PROCESS_ID;
  }

  // Production mode — check explicit BUILD_ID override first.
  const explicitBuildId = process.env.BUILD_ID;
  if (explicitBuildId !== undefined && explicitBuildId !== "") {
    const trimmed = explicitBuildId.trim();
    if (!trimmed || PLACEHOLDER_COMMITS.has(trimmed)) {
      throw new Error(
        `BUILD_ID "${explicitBuildId}" is a placeholder value and cannot be used as a ` +
          `production build ID. Set BUILD_ID to a real identifier (e.g. a Docker image ` +
          `digest, CI run ID, or any unique string that identifies this exact artifact).`,
      );
    }
    return trimmed;
  }

  // Validate the commit parameter.
  const trimmedCommit = (commit ?? "").trim();
  if (!trimmedCommit || PLACEHOLDER_COMMITS.has(trimmedCommit)) {
    throw new Error(
      `Commit "${commit}" is a placeholder and cannot be used as a production build ID. ` +
        `Fix: ensure RAILWAY_GIT_COMMIT_SHA, RENDER_GIT_COMMIT, or GIT_COMMIT_SHA is set ` +
        `in your build environment, or supply BUILD_ID explicitly.`,
    );
  }

  // Canonical config object (keys sorted for stability).
  const canonicalConfig: Record<string, string | undefined> = {};
  for (const key of BUNDLE_CONFIG_KEYS) {
    canonicalConfig[key] = publicConfig[key];
  }

  const input = trimmedCommit + "\0" + JSON.stringify(canonicalConfig);
  return createHash("sha256").update(input, "utf8").digest("hex");
}

/**
 * Vite plugin that:
 * (a) defines `__BUILD_ID__` and `__BUILD_ENVIRONMENT__` for the bundle,
 * (b) emits `dist/build-meta.json` with build provenance,
 * (c) emits `dist/release/policy.json` as a deterministic authority fixture
 *     so the serving infrastructure has a valid policy document from day one.
 */
export function buildIdentityPlugin(): Plugin {
  let resolvedBuildId = "";
  let resolvedEnvironment = "";
  let resolvedCommit = "";

  return {
    name: "build-identity",

    config(_, { mode }) {
      resolvedCommit = resolveCommitSha();
      resolvedEnvironment = process.env.VITE_ENVIRONMENT ?? mode;

      const publicConfig: Record<string, string | undefined> = {};
      for (const key of BUNDLE_CONFIG_KEYS) {
        publicConfig[key] = process.env[key];
      }

      resolvedBuildId = computeBuildId({ commit: resolvedCommit, publicConfig, mode });

      return {
        define: {
          __BUILD_ID__: JSON.stringify(resolvedBuildId),
          __BUILD_ENVIRONMENT__: JSON.stringify(resolvedEnvironment),
        },
      };
    },

    generateBundle() {
      const builtAt = new Date().toISOString();
      const releaseRevision = Number(process.env.RELEASE_REVISION ?? 1);

      // dist/build-meta.json — artifact provenance
      this.emitFile({
        type: "asset",
        fileName: "build-meta.json",
        source: JSON.stringify(
          {
            schema: "exam-generation.build-meta/1",
            build_id: resolvedBuildId,
            environment: resolvedEnvironment,
            commit: resolvedCommit,
            built_at: builtAt,
          },
          null,
          2,
        ),
      });

      // dist/release/policy.json — deterministic authority fixture
      this.emitFile({
        type: "asset",
        fileName: "release/policy.json",
        source: JSON.stringify(
          {
            schema: "exam-generation.release-policy/1",
            environment: resolvedEnvironment,
            release_revision: releaseRevision,
            released_build_id: resolvedBuildId,
            admission: "open",
            supported_recovery_formats: [],
          },
          null,
          2,
        ),
      });
    },
  };
}
