/**
 * Release detector store — issue #770.
 *
 * Plain zustand store holding the current artifact-comparison state.
 * The store never calls location.reload, never touches workspace store
 * operations, and never submits anything.
 */
import { create } from "zustand";
import { compareArtifact, isAdmissionPaused, parseReleasePolicy } from "./policy";

export type ReleaseStatus =
  | "checking"
  | "current"
  | "update-required"
  | "paused"
  | "unavailable";

export type FailureReason =
  | "offline"
  | "timeout"
  | "malformed"
  | "unknown_schema"
  | "environment_mismatch"
  | "http";

export interface ReleaseState {
  status: ReleaseStatus;
  /** Sticky: once a required build id is known it is retained across failures. */
  requiredBuildId: string | null;
  releaseRevision: number | null;
  lastCheckedAt: number | null;
  lastFailure: FailureReason | null;

  /** Coalesced check: at most one in-flight. */
  checkNow(): Promise<void>;
}

interface SuccessResult {
  status: ReleaseStatus;
  requiredBuildId: string | null;
  releaseRevision: number;
}

const POLICY_URL = "/release/policy.json";
const TIMEOUT_MS = 5000;

// Detector state outside the zustand store so they aren't persisted in
// snapshots but also reset with resetReleaseDetector() in tests.
let _requestSeq = 0;
let _inFlight: Promise<void> | null = null;

/**
 * Reset coalescing state for test isolation.
 * NOT for production use.
 */
export function resetReleaseDetector(): void {
  _requestSeq = 0;
  _inFlight = null;
}

export const useReleaseStore = create<ReleaseState>((_set, get) => ({
  status: "checking",
  requiredBuildId: null,
  releaseRevision: null,
  lastCheckedAt: null,
  lastFailure: null,

  checkNow(): Promise<void> {
    if (_inFlight !== null) return _inFlight;

    _inFlight = _doCheck(get).finally(() => {
      _inFlight = null;
    });

    return _inFlight;
  },
}));

async function _doCheck(getState: () => ReleaseState): Promise<void> {
  const thisSeq = ++_requestSeq;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let failureReason: FailureReason | null = null;
  let successResult: SuccessResult | undefined;

  try {
    const response = await fetch(POLICY_URL, {
      cache: "no-store",
      signal: controller.signal,
    });

    if (thisSeq !== _requestSeq) return; // stale — ignore

    if (!response.ok) {
      failureReason = "http";
      throw new Error(`HTTP ${response.status}`);
    }

    const raw: unknown = await response.json();

    if (thisSeq !== _requestSeq) return; // stale

    const parseResult = parseReleasePolicy(raw, __BUILD_ENVIRONMENT__);

    if (!parseResult.ok) {
      failureReason = parseResult.reason as FailureReason;
      throw new Error(parseResult.reason);
    }

    const { policy } = parseResult;

    if (isAdmissionPaused(policy)) {
      successResult = {
        status: "paused",
        requiredBuildId: getState().requiredBuildId,
        releaseRevision: policy.release_revision,
      };
    } else {
      const cmp = compareArtifact(__BUILD_ID__, policy);
      successResult = {
        status: cmp === "update-required" ? "update-required" : "current",
        requiredBuildId:
          cmp === "update-required" ? policy.released_build_id : null,
        releaseRevision: policy.release_revision,
      };
    }
  } catch (err) {
    if (thisSeq !== _requestSeq) return; // stale

    if (!failureReason) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      failureReason = isAbort ? "timeout" : "offline";
    }

    // Retain a previously known update requirement
    const prev = getState();
    if (prev.requiredBuildId !== null && prev.status === "update-required") {
      useReleaseStore.setState({ lastFailure: failureReason, lastCheckedAt: Date.now() });
      return;
    }

    useReleaseStore.setState({
      status: "unavailable",
      lastFailure: failureReason,
      lastCheckedAt: Date.now(),
    });
    return;
  } finally {
    clearTimeout(timer);
  }

  if (thisSeq !== _requestSeq || successResult === undefined) return;

  useReleaseStore.setState({
    status: successResult.status,
    requiredBuildId: successResult.requiredBuildId,
    releaseRevision: successResult.releaseRevision,
    lastCheckedAt: Date.now(),
    lastFailure: null,
  });
}
