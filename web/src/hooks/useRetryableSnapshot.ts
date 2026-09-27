/**
 * useRetryableSnapshot — shared retry-snapshot ref logic (#752/#753).
 *
 * All three ODT export surfaces (QuestionCard, GeneratePage batch, HistoryDetail)
 * follow the same pattern:
 *   - On a fresh click: capture a new snapshot and store it in a ref.
 *   - On retry (feedback state === "failed"): reuse the stored ref so the ODT
 *     image is identical to what the user saw at click time, even if a new
 *     revision arrived between the failure and the retry.
 *
 * This hook extracts that ref + `getOrCapture` logic into one place.
 *
 * @template T  The snapshot type (e.g. QuestionSnapshot or
 *              [QuestionSnapshot[], boolean] for batch exports).
 */
import { useRef, useCallback } from "react";

export interface UseRetryableSnapshotReturn<T> {
  /**
   * The ref holding the last captured snapshot (null before the first capture).
   * Read this directly only in tests or for debugging; prefer `getOrCapture`.
   */
  lastRef: React.MutableRefObject<T | null>;

  /**
   * On retry (`isFailed === true` and a prior snapshot exists) returns the
   * stored snapshot unchanged.  Otherwise calls `captureNew()`, stores the
   * non-null result in the ref, and returns it.
   *
   * A null result from `captureNew()` is returned as-is and does NOT overwrite
   * the stored ref, so a subsequent retry can still reuse the last good capture.
   */
  getOrCapture: (isFailed: boolean, captureNew: () => T | null) => T | null;
}

export function useRetryableSnapshot<T>(): UseRetryableSnapshotReturn<T> {
  const lastRef = useRef<T | null>(null);

  const getOrCapture = useCallback(
    (isFailed: boolean, captureNew: () => T | null): T | null => {
      if (isFailed && lastRef.current !== null) {
        return lastRef.current;
      }
      const snapshot = captureNew();
      if (snapshot !== null) {
        lastRef.current = snapshot;
      }
      return snapshot;
    },
    [],
  );

  return { lastRef, getOrCapture };
}
