import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildIdentityPlugin, computeBuildId } from "./buildIdentity";

// Save and restore env around each test
let savedEnv: Record<string, string | undefined> = {};

function setEnv(vars: Record<string, string | undefined>) {
  for (const [k, v] of Object.entries(vars)) {
    savedEnv[k] = process.env[k];
    if (v === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = v;
    }
  }
}

function restoreEnv() {
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = v;
    }
  }
  savedEnv = {};
}

beforeEach(() => {
  // Clean commit and build-id env before each test
  setEnv({
    BUILD_ID: undefined,
    RAILWAY_GIT_COMMIT_SHA: undefined,
    RENDER_GIT_COMMIT: undefined,
    GIT_COMMIT_SHA: undefined,
    RELEASE_REVISION: undefined,
    VITE_ENVIRONMENT: undefined,
    VITE_IS_STAGING: undefined,
    VITE_SENTRY_DSN: undefined,
    VITE_SENTRY_RELEASE: undefined,
  });
});

afterEach(() => {
  restoreEnv();
});

const REAL_COMMIT = "abc123def456789012345678901234567890abcd";

describe("computeBuildId", () => {
  it("same commit + different public config -> different ids", () => {
    const config1 = {
      VITE_IS_STAGING: "true",
      VITE_SENTRY_DSN: undefined,
      VITE_SENTRY_RELEASE: undefined,
      VITE_ENVIRONMENT: "production",
    };
    const config2 = {
      VITE_IS_STAGING: "false",
      VITE_SENTRY_DSN: undefined,
      VITE_SENTRY_RELEASE: undefined,
      VITE_ENVIRONMENT: "production",
    };

    const id1 = computeBuildId({ commit: REAL_COMMIT, publicConfig: config1, mode: "production" });
    const id2 = computeBuildId({ commit: REAL_COMMIT, publicConfig: config2, mode: "production" });

    expect(id1).not.toBe(id2);
  });

  it("same inputs -> same id", () => {
    const config = {
      VITE_IS_STAGING: "true",
      VITE_SENTRY_DSN: "https://dsn@sentry.io/123",
      VITE_SENTRY_RELEASE: "v1.0.0",
      VITE_ENVIRONMENT: "production",
    };

    const id1 = computeBuildId({ commit: REAL_COMMIT, publicConfig: config, mode: "production" });
    const id2 = computeBuildId({ commit: REAL_COMMIT, publicConfig: config, mode: "production" });

    expect(id1).toBe(id2);
    expect(id1.length).toBeGreaterThanOrEqual(16);
  });

  it("production + placeholder commit throws with a message naming the fix", () => {
    const placeholders = ["unknown", "dev", "local", "HEAD", ""];
    for (const placeholder of placeholders) {
      expect(
        () => computeBuildId({ commit: placeholder, publicConfig: {}, mode: "production" }),
        `expected throw for placeholder "${placeholder}"`,
      ).toThrow(/BUILD_ID|RAILWAY_GIT_COMMIT_SHA|RENDER_GIT_COMMIT|GIT_COMMIT_SHA/);
    }
  });

  it("explicit BUILD_ID env wins over commit computation", () => {
    process.env.BUILD_ID = "my-explicit-build-id-12345";
    const id = computeBuildId({ commit: REAL_COMMIT, publicConfig: {}, mode: "production" });
    expect(id).toBe("my-explicit-build-id-12345");
  });

  it("explicit BUILD_ID that is a placeholder throws", () => {
    process.env.BUILD_ID = "unknown";
    expect(() =>
      computeBuildId({ commit: REAL_COMMIT, publicConfig: {}, mode: "production" }),
    ).toThrow();
  });

  it("different commits with same config -> different ids", () => {
    const config = { VITE_IS_STAGING: "false" };
    const id1 = computeBuildId({ commit: REAL_COMMIT, publicConfig: config, mode: "production" });
    const id2 = computeBuildId({
      commit: "deadbeef1234567890abcdef1234567890abcdef",
      publicConfig: config,
      mode: "production",
    });
    expect(id1).not.toBe(id2);
  });

  it("non-production mode returns dev- prefix without throwing for placeholder commit", () => {
    const id = computeBuildId({ commit: "unknown", publicConfig: {}, mode: "development" });
    expect(id).toMatch(/^dev-/);
  });

  it("non-production mode returns same value per-process (stable)", () => {
    const id1 = computeBuildId({ commit: "", publicConfig: {}, mode: "development" });
    const id2 = computeBuildId({ commit: "", publicConfig: {}, mode: "development" });
    expect(id1).toBe(id2);
  });
});

describe("buildIdentityPlugin", () => {
  it("generateBundle emits build-meta.json and release/policy.json with matching build_id", () => {
    process.env.GIT_COMMIT_SHA = REAL_COMMIT;
    process.env.RELEASE_REVISION = "3";

    const plugin = buildIdentityPlugin();

    // Trigger config hook to compute build id
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const configResult = (plugin.config as any)({}, { mode: "production" });
    const buildId: string = JSON.parse(configResult.define.__BUILD_ID__ as string);

    const emitted: Array<{ fileName: string; source: string }> = [];
    const fakeThis = {
      emitFile(file: { type: string; fileName: string; source: string }) {
        emitted.push({ fileName: file.fileName, source: file.source });
      },
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (plugin.generateBundle as any).call(fakeThis, {}, {}, false);

    const buildMeta = emitted.find((f) => f.fileName === "build-meta.json");
    const policyFile = emitted.find((f) => f.fileName === "release/policy.json");

    expect(buildMeta).toBeDefined();
    expect(policyFile).toBeDefined();

    const buildMetaJson = JSON.parse(buildMeta!.source) as {
      schema: string;
      build_id: string;
      environment: string;
      commit: string;
      built_at: string;
    };
    const policyJson = JSON.parse(policyFile!.source) as {
      schema: string;
      build_id?: string;
      released_build_id: string;
      release_revision: number;
      environment: string;
      admission: string;
      supported_recovery_formats: string[];
      reader_version: string;
    };

    // Both files must share the same build_id
    expect(buildMetaJson.build_id).toBe(buildId);
    expect(policyJson.released_build_id).toBe(buildId);
    expect(buildMetaJson.build_id).toBe(policyJson.released_build_id);

    // Correct schemas
    expect(buildMetaJson.schema).toBe("exam-generation.build-meta/1");
    expect(policyJson.schema).toBe("exam-generation.release-policy/1");

    // Policy fields
    expect(policyJson.release_revision).toBe(3);
    expect(policyJson.admission).toBe("open");
    expect(policyJson.supported_recovery_formats).toEqual([]);
    expect(policyJson.reader_version).toBe("reader-1");

    // Build meta fields
    expect(buildMetaJson.commit).toBe(REAL_COMMIT);
    expect(buildMetaJson.built_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
