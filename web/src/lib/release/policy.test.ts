import { describe, expect, it } from "vitest";
import {
  compareArtifact,
  isAdmissionPaused,
  parseReleasePolicy,
  RELEASE_POLICY_SCHEMA,
} from "./policy";

const VALID_POLICY = {
  schema: RELEASE_POLICY_SCHEMA,
  environment: "production",
  release_revision: 5,
  released_build_id: "abc123def456789012345678901234567890abcd",
  admission: "open",
  supported_recovery_formats: [],
};

describe("parseReleasePolicy", () => {
  it("parses a valid policy document", () => {
    const result = parseReleasePolicy(VALID_POLICY, "production");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.policy.release_revision).toBe(5);
      expect(result.policy.released_build_id).toBe(
        "abc123def456789012345678901234567890abcd",
      );
      expect(result.policy.admission).toBe("open");
    }
  });

  it("rejects an unknown schema", () => {
    const result = parseReleasePolicy(
      { ...VALID_POLICY, schema: "exam-generation.release-policy/2" },
      "production",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unknown_schema");
  });

  it("rejects a document with missing required fields", () => {
    const { release_revision: _omit, ...missing } = VALID_POLICY;
    const result = parseReleasePolicy(missing, "production");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects a document where admission is not a valid value", () => {
    const result = parseReleasePolicy(
      { ...VALID_POLICY, admission: "unknown_state" },
      "production",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects when environment does not match", () => {
    const result = parseReleasePolicy(VALID_POLICY, "staging");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("environment_mismatch");
  });

  it("rejects non-object input", () => {
    const result = parseReleasePolicy("not an object", "production");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects null input", () => {
    const result = parseReleasePolicy(null, "production");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects a policy where release_revision is not a number", () => {
    const result = parseReleasePolicy(
      { ...VALID_POLICY, release_revision: "5" },
      "production",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("accepts paused and preparing admission values", () => {
    for (const admission of ["paused", "preparing"] as const) {
      const result = parseReleasePolicy({ ...VALID_POLICY, admission }, "production");
      expect(result.ok).toBe(true);
    }
  });
});

describe("compareArtifact", () => {
  const POLICY_A = {
    ...VALID_POLICY,
    released_build_id: "build-A",
  };

  it("returns current when build IDs match", () => {
    expect(compareArtifact("build-A", POLICY_A)).toBe("current");
  });

  it("returns update-required when build IDs differ", () => {
    expect(compareArtifact("build-B", POLICY_A)).toBe("update-required");
  });

  it("rollback: higher release_revision but same (earlier) build ID compares current for A", () => {
    // release_revision went from 7 to 8, but released_build_id rolled back to A
    const rollbackPolicy = {
      ...VALID_POLICY,
      release_revision: 8,
      released_build_id: "build-A",
    };
    expect(compareArtifact("build-A", rollbackPolicy)).toBe("current");
  });

  it("never treats a Sentry-release-looking string as equal to a different build ID", () => {
    const sentryRelease = "abc123def456789012345678901234567890abcd@1.0.0+build.1";
    expect(compareArtifact(sentryRelease, POLICY_A)).toBe("update-required");
  });

  it("commit-hash ordering is never consulted — only equality", () => {
    // Two different hashes should compare update-required regardless of
    // lexicographic ordering
    const hashA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const hashB = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const policy = { ...VALID_POLICY, released_build_id: hashB };

    // hashA < hashB lexicographically but we only use equality
    expect(compareArtifact(hashA, policy)).toBe("update-required");
    expect(compareArtifact(hashB, policy)).toBe("current");
  });
});

describe("isAdmissionPaused", () => {
  it("returns false for open admission", () => {
    expect(isAdmissionPaused({ ...VALID_POLICY, admission: "open" })).toBe(false);
  });

  it("returns true for paused admission", () => {
    expect(isAdmissionPaused({ ...VALID_POLICY, admission: "paused" })).toBe(true);
  });

  it("returns true for preparing admission", () => {
    expect(isAdmissionPaused({ ...VALID_POLICY, admission: "preparing" })).toBe(true);
  });
});
