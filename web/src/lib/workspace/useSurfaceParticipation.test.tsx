import { StrictMode } from "react";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetWorkspaceStoreForTests, useWorkspaceStore, type SurfaceId, type SurfaceParticipation } from "./workspaceStore";
import type { ModificationWorkspaceSnapshot } from "./adapters/types";
import { useSurfaceParticipation } from "./useSurfaceParticipation";

beforeEach(() => resetWorkspaceStoreForTests());

const ready = { readiness: "ready" as const, hasEditableState: false, hasReceivedResults: false };

describe("useSurfaceParticipation", () => {
  it("registers on mount, patches on change, unregisters on unmount", () => {
    const { rerender, unmount } = renderHook(
      ({ participation }: { participation: Omit<SurfaceParticipation, "id"> }) =>
        useSurfaceParticipation("history.detail", participation),
      { initialProps: { participation: { ...ready, readiness: "hydrating" } } },
    );
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("hydrating");
    rerender({ participation: { ...ready, hasEditableState: true, hasReceivedResults: true } });
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toMatchObject({
      readiness: "ready", hasEditableState: true, hasReceivedResults: true,
    });
    unmount();
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toBeUndefined();
  });

  it("keeps the latest export seam callable from the store and can remove it", () => {
    const snapshot: ModificationWorkspaceSnapshot = {
      kind: "modification", version: 1, recordId: "r1", questionId: "q1", annotations: [], replacement: null,
    };
    const { rerender } = renderHook(
      ({ exportWorkspace }: Pick<SurfaceParticipation, "exportWorkspace">) =>
        useSurfaceParticipation("history.modification", { ...ready, exportWorkspace }),
      { initialProps: { exportWorkspace: () => snapshot } },
    );
    expect(useWorkspaceStore.getState().surfaces["history.modification"]?.exportWorkspace?.()).toEqual(snapshot);
    rerender({ exportWorkspace: () => null });
    expect(useWorkspaceStore.getState().surfaces["history.modification"]?.exportWorkspace?.()).toBeNull();
    rerender({ exportWorkspace: undefined });
    expect(useWorkspaceStore.getState().surfaces["history.modification"]?.exportWorkspace).toBeUndefined();
  });

  it("does not notify subscribers when only the participation object identity changes", () => {
    const { rerender } = renderHook(() => useSurfaceParticipation("history.detail", { ...ready }));
    const listener = vi.fn();
    const unsubscribe = useWorkspaceStore.subscribe(listener);
    rerender();
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("moves registration when the surface id changes", () => {
    const { rerender, unmount } = renderHook(
      ({ id }: { id: SurfaceId }) => useSurfaceParticipation(id, ready),
      { initialProps: { id: "history.detail" } },
    );
    rerender({ id: "history.list" });
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toBeUndefined();
    expect(useWorkspaceStore.getState().surfaces["history.list"]?.readiness).toBe("ready");
    unmount();
    expect(useWorkspaceStore.getState().surfaces).toEqual({});
  });

  it("survives StrictMode mount cleanup and unregisters after a patch", () => {
    const { rerender, unmount } = renderHook(
      ({ edited }) => useSurfaceParticipation("history.modification", { ...ready, hasEditableState: edited }),
      { initialProps: { edited: false }, wrapper: StrictMode },
    );
    expect(Object.keys(useWorkspaceStore.getState().surfaces)).toEqual(["history.modification"]);
    rerender({ edited: true });
    expect(useWorkspaceStore.getState().surfaces["history.modification"]?.hasEditableState).toBe(true);
    unmount();
    expect(useWorkspaceStore.getState().surfaces).toEqual({});
  });
});
