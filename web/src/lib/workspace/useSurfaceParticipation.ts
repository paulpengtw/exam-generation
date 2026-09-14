import { useEffect } from "react";
import { useWorkspaceStore } from "./workspaceStore";
import type { SurfaceId, SurfaceParticipation } from "./workspaceStore";

export function useSurfaceParticipation(
  id: SurfaceId,
  participation: Omit<SurfaceParticipation, "id">,
): void {
  const { readiness, hasEditableState, hasReceivedResults, exportWorkspace } = participation;
  useEffect(() => {
    return useWorkspaceStore.getState().registerSurface({
      id, readiness, hasEditableState, hasReceivedResults, exportWorkspace,
    });
    // Register once per id; the effect below patches changing values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    useWorkspaceStore.getState().updateSurface(id, {
      readiness, hasEditableState, hasReceivedResults, exportWorkspace,
    });
  }, [id, readiness, hasEditableState, hasReceivedResults, exportWorkspace]);
}
