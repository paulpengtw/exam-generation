/**
 * Recovery store — boots on app start, reads the tab pointer, loads and
 * parses the stored snapshot, and exposes it for ParamForm to consume.
 *
 * Issue #772.
 */
import { create } from "zustand";
import { parseRecoverySnapshot } from "./format";
import type { RecoverySnapshotV1 } from "./format";
import {
  loadTabPointer,
  loadSnapshot,
  deleteSnapshot,
  clearTabPointer,
} from "./storage";
import { useAuthStore } from "../../store/authStore";

export type RecoveryBlockedReason = "wrong_account" | "wrong_origin" | "environment_mismatch";

export interface RecoveryState {
  /** Parsed snapshot waiting for the form to consume. */
  pending: RecoverySnapshotV1 | null;
  /** Set when a snapshot exists but cannot be loaded for this session. */
  blocked: RecoveryBlockedReason | null;

  acknowledgeRecovery(): void;
  discardRecovery(): void;
}

export const useRecoveryStore = create<RecoveryState>((set, get) => ({
  pending: null,
  blocked: null,

  acknowledgeRecovery() {
    set({ pending: null });
  },

  discardRecovery() {
    const { pending } = get();
    if (pending) {
      deleteSnapshot(pending.account_id, pending.snapshot_id);
      clearTabPointer();
    }
    set({ pending: null, blocked: null });
  },
}));

export interface InitRecoveryOptions {
  currentRoute: string;
  origin: string;
  environment: string;
}

/**
 * Called once at app boot (or on sign-in) to attempt restoring a saved snapshot.
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
      useRecoveryStore.setState({ blocked: "wrong_account" });
    }
    // Other failures: silent — don't hydrate, don't block
    return;
  }

  useRecoveryStore.setState({ pending: result.snapshot, blocked: null });
}

/**
 * Reset store for tests.
 * NOT for production use.
 */
export function resetRecoveryStoreForTests(): void {
  useRecoveryStore.setState({ pending: null, blocked: null });
}
