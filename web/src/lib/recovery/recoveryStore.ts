/**
 * Recovery store — boots on app start, reads the tab pointer, loads and
 * parses the stored snapshot, and exposes it for ParamForm to consume.
 *
 * Issue #772.  Identity hardening in issue #776.
 */
import { create } from "zustand";
import { parseRecoverySnapshot } from "./format";
import type { RecoverySnapshotV1 } from "./format";
import {
  loadTabPointer,
  loadSnapshot,
  deleteSnapshot,
  clearTabPointer,
  claimSnapshot,
  releaseSnapshotClaim,
  getOrCreateTabId,
} from "./storage";
import { useAuthStore } from "../../store/authStore";

export type RecoveryBlockedReason = "wrong_account" | "wrong_origin" | "environment_mismatch";

export interface RecoveryState {
  /** Parsed snapshot waiting for the form to consume. */
  pending: RecoverySnapshotV1 | null;
  /** Set when a snapshot exists but cannot be loaded for this session. */
  blocked: RecoveryBlockedReason | null;
  /** The tab ID that won the claim for the pending snapshot. */
  claimedTabId: string | null;
  /** The snapshot ID for which a claim is held (released on ack/discard). */
  claimedSnapshotId: string | null;

  acknowledgeRecovery(): void;
  discardRecovery(): void;
}

export const useRecoveryStore = create<RecoveryState>((set, get) => ({
  pending: null,
  blocked: null,
  claimedTabId: null,
  claimedSnapshotId: null,

  acknowledgeRecovery() {
    const { claimedSnapshotId } = get();
    if (claimedSnapshotId) {
      releaseSnapshotClaim(claimedSnapshotId);
    }
    set({ pending: null, claimedTabId: null, claimedSnapshotId: null });
  },

  discardRecovery() {
    const { pending, claimedSnapshotId } = get();
    if (pending) {
      deleteSnapshot(pending.account_id, pending.snapshot_id);
      clearTabPointer();
    }
    if (claimedSnapshotId) {
      releaseSnapshotClaim(claimedSnapshotId);
    }
    set({ pending: null, blocked: null, claimedTabId: null, claimedSnapshotId: null });
  },
}));

export interface InitRecoveryOptions {
  currentRoute: string;
  origin: string;
  environment: string;
}

/**
 * Called once at app boot (or on sign-in) to attempt restoring a saved snapshot.
 * Synchronous variant — does not perform tab-collision detection.
 * For full identity-hardening with collision detection, call initRecoveryStoreAsync.
 */
export function initRecoveryStore(opts: InitRecoveryOptions): void {
  const pointer = loadTabPointer();
  if (!pointer) return;

  const user = useAuthStore.getState().user;

  // If not signed in, keep the pointer but do nothing until sign-in
  if (!user) return;

  // If route doesn't match, skip (snapshot is for a different page)
  if (pointer.route !== opts.currentRoute) return;

  // Load the snapshot
  const raw = loadSnapshot(pointer.account_id, pointer.snapshot_id);
  if (!raw) return;

  const result = parseRecoverySnapshot(raw, {
    expectedAccountId: user.id,
    expectedOrigin: opts.origin,
    expectedEnvironment: opts.environment,
  });

  if (!result.ok) {
    if (result.reason === "wrong_account") {
      // Snapshot exists but belongs to a different account — block without
      // exposing contents.  Do NOT set pending.
      useRecoveryStore.setState({ blocked: "wrong_account" });
    }
    // Other failures: silent — don't hydrate, don't block
    return;
  }

  useRecoveryStore.setState({ pending: result.snapshot, blocked: null });
}

/**
 * Full async variant (issue #776).
 *
 * Extends the synchronous boot with a transactional restoration claim so two
 * simultaneous tabs cannot both hydrate the same snapshot.
 *
 * Steps:
 *  1. Read pointer → validate user + route.
 *  2. Resolve the current tab ID.
 *  3. Write a claim (tab_id + nonce) and read it back; only continue when
 *     the nonce round-trips (this tab won the race).
 *  4. Parse and validate the snapshot.
 *  5. Set pending on success, blocked on wrong_account.
 *
 * A failed claim leaves the snapshot and pointer on disk so the owning tab
 * can hydrate it.  Failed hydration also leaves the snapshot on disk.
 */
export async function initRecoveryStoreAsync(opts: InitRecoveryOptions): Promise<void> {
  const pointer = loadTabPointer();
  if (!pointer) return;

  const user = useAuthStore.getState().user;
  if (!user) return;

  if (pointer.route !== opts.currentRoute) return;

  // Resolve tab ID (does NOT do collision detection by itself — the caller is
  // responsible for calling startTabCollisionListener after identity resolution)
  const tabId = getOrCreateTabId();

  // Transactional claim — prevents two tabs from both hydrating
  const { won } = await claimSnapshot(tabId, pointer.snapshot_id);
  if (!won) {
    // Another tab owns this snapshot — leave it alone
    return;
  }

  const raw = loadSnapshot(pointer.account_id, pointer.snapshot_id);
  if (!raw) {
    releaseSnapshotClaim(pointer.snapshot_id);
    return;
  }

  const result = parseRecoverySnapshot(raw, {
    expectedAccountId: user.id,
    expectedOrigin: opts.origin,
    expectedEnvironment: opts.environment,
  });

  if (!result.ok) {
    releaseSnapshotClaim(pointer.snapshot_id);
    if (result.reason === "wrong_account") {
      useRecoveryStore.setState({ blocked: "wrong_account" });
    }
    return;
  }

  useRecoveryStore.setState({
    pending: result.snapshot,
    blocked: null,
    claimedTabId: tabId,
    claimedSnapshotId: pointer.snapshot_id,
  });
}

/**
 * Reset store for tests.
 * NOT for production use.
 */
export function resetRecoveryStoreForTests(): void {
  useRecoveryStore.setState({
    pending: null,
    blocked: null,
    claimedTabId: null,
    claimedSnapshotId: null,
  });
}
