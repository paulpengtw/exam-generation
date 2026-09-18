/**
 * Subscribes to workspaceStore.updateIntent and fires runSaveAndUpdate
 * when the intent transitions to "active" (all operations have settled).
 * Issue #777.
 */
import { useEffect } from "react";
import { useWorkspaceStore } from "../workspace/workspaceStore";
import { runSaveAndUpdate } from "./saveAndUpdate";

export function useQueuedUpdateIntent(navigate?: () => void): void {
  useEffect(() => {
    return useWorkspaceStore.subscribe((state, prev) => {
      if (
        state.updateIntent?.kind === "active" &&
        prev.updateIntent?.kind !== "active"
      ) {
        // Clear intent before firing to prevent double-fire
        useWorkspaceStore.getState().cancelUpdateIntent();
        void runSaveAndUpdate(navigate ? { navigate } : undefined);
      }
    });
  }, [navigate]);
}
