/**
 * Release-policy reader — issue #770.
 *
 * Parses the deterministic authority fixture served at /release/policy.json
 * and compares it against the running artifact's build ID.
 *
 * Artifact comparison is string-equality only: a rollback has a higher
 * release_revision but targets an earlier build; commit-hash ordering is
 * never consulted.
 */

export const RELEASE_POLICY_SCHEMA = "exam-generation.release-policy/1";

/** Admission states understood by this schema version. */
type Admission = "open" | "paused" | "preparing";

export interface ReleasePolicy {
  schema: typeof RELEASE_POLICY_SCHEMA;
  environment: string;
  release_revision: number;
  released_build_id: string;
  admission: Admission;
  supported_recovery_formats: string[];
  reader_version?: string;
}

type ParseOk = { ok: true; policy: ReleasePolicy };
type ParseFail = {
  ok: false;
  reason: "malformed" | "unknown_schema" | "environment_mismatch";
};

/**
 * Parse and validate raw JSON (already decoded from fetch) against the
 * release-policy schema.
 *
 * - `malformed`: document is not an object, missing required fields, or
 *   has wrong types / invalid enum values.
 * - `unknown_schema`: the `schema` field is present but not recognised.
 * - `environment_mismatch`: the document's `environment` does not match
 *   `expectedEnvironment`.
 *
 * Checks run in the above order so the most actionable reason is returned.
 */
export function parseReleasePolicy(
  input: unknown,
  expectedEnvironment: string,
): ParseOk | ParseFail {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return { ok: false, reason: "malformed" };
  }

  const doc = input as Record<string, unknown>;

  // Schema check
  if (doc.schema !== RELEASE_POLICY_SCHEMA) {
    // Distinguish unknown schema from other malform: if the field exists but
    // is a non-empty string, it's an unknown schema version.
    if (typeof doc.schema === "string" && doc.schema.length > 0) {
      return { ok: false, reason: "unknown_schema" };
    }
    return { ok: false, reason: "malformed" };
  }

  // Required field type checks
  if (
    typeof doc.environment !== "string" ||
    doc.environment.length === 0 ||
    typeof doc.release_revision !== "number" ||
    !Number.isInteger(doc.release_revision) ||
    doc.release_revision < 1 ||
    typeof doc.released_build_id !== "string" ||
    doc.released_build_id.length === 0 ||
    typeof doc.admission !== "string" ||
    !Array.isArray(doc.supported_recovery_formats)
  ) {
    return { ok: false, reason: "malformed" };
  }

  // Admission enum
  const VALID_ADMISSIONS: ReadonlySet<string> = new Set(["open", "paused", "preparing"]);
  if (!VALID_ADMISSIONS.has(doc.admission)) {
    return { ok: false, reason: "malformed" };
  }

  // supported_recovery_formats must be an array of strings
  if (!(doc.supported_recovery_formats as unknown[]).every((f) => typeof f === "string")) {
    return { ok: false, reason: "malformed" };
  }

  if (doc.reader_version !== undefined &&
      (typeof doc.reader_version !== "string" || doc.reader_version.length === 0)) {
    return { ok: false, reason: "malformed" };
  }

  // Environment check
  if (doc.environment !== expectedEnvironment) {
    return { ok: false, reason: "environment_mismatch" };
  }

  return {
    ok: true,
    policy: {
      schema: RELEASE_POLICY_SCHEMA,
      environment: doc.environment,
      release_revision: doc.release_revision,
      released_build_id: doc.released_build_id,
      admission: doc.admission as Admission,
      supported_recovery_formats: doc.supported_recovery_formats as string[],
      ...(doc.reader_version !== undefined ? { reader_version: doc.reader_version } : {}),
    },
  };
}

/**
 * Compare the running artifact's build ID against the policy's released
 * build ID.
 *
 * Returns `'current'` when they are equal; `'update-required'` otherwise.
 * Comparison is strict string equality only — never lexicographic ordering
 * of commit hashes or Sentry release strings.
 */
export function compareArtifact(
  currentBuildId: string,
  policy: Pick<ReleasePolicy, "released_build_id">,
): "current" | "update-required" {
  return currentBuildId === policy.released_build_id ? "current" : "update-required";
}

/**
 * Returns true when `policy.admission` is `'paused'` or `'preparing'`
 * (any non-open state that warrants displaying the paused notice).
 */
export function isAdmissionPaused(policy: Pick<ReleasePolicy, "admission">): boolean {
  return policy.admission === "paused" || policy.admission === "preparing";
}
