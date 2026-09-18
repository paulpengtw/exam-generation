/**
 * Queued update intent — unit tests.
 * Issue #777.
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  useWorkspaceStore,
  resetWorkspaceStoreForTests,
} from "../workspace/workspaceStore";

beforeEach(() => {
  resetWorkspaceStoreForTests();
});

describe("Queued update intent", () => {
  it("unit: queue intent sets kind=queued when operations are active", () => {
    const handle = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    useWorkspaceStore.getState().queueUpdateIntent();
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });
    handle.end("completed");
  });

  it("unit: queueUpdateIntent does nothing when no operations are running", () => {
    useWorkspaceStore.getState().queueUpdateIntent();
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();
  });

  it("unit: cancel intent clears to null, leaves operations untouched", () => {
    const handle = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    useWorkspaceStore.getState().queueUpdateIntent();
    useWorkspaceStore.getState().cancelUpdateIntent();
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();
    expect(useWorkspaceStore.getState().operations).toHaveLength(1);
    handle.end("completed");
  });

  it("unit: last operation end transitions queued→active", () => {
    const h1 = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    const h2 = useWorkspaceStore.getState().beginOperation("export_odt", "generate.results");
    useWorkspaceStore.getState().queueUpdateIntent();
    h1.end("completed");
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });
    h2.end("completed");
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "active" });
  });

  it("unit: detection only: beginOperation without queueUpdateIntent does not queue intent", () => {
    const handle = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();
    handle.end("completed");
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();
  });
});
