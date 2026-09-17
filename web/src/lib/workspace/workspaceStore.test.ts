import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isRefreshSafe,
  resetWorkspaceStoreForTests,
  useWorkspaceStore,
  type SurfaceParticipation,
} from "./workspaceStore";

const ready = { readiness: "ready" as const, hasEditableState: false, hasReceivedResults: false };

beforeEach(() => resetWorkspaceStoreForTests());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("registerSurface", () => {
  it("registers, patches and unregisters a surface", () => {
    const unregister = useWorkspaceStore.getState().registerSurface({ id: "generate.results", ...ready });
    const original = useWorkspaceStore.getState().surfaces["generate.results"];
    expect(original?.readiness).toBe("ready");
    useWorkspaceStore.getState().updateSurface("generate.results", { hasReceivedResults: true });
    expect(useWorkspaceStore.getState().surfaces["generate.results"]?.hasReceivedResults).toBe(true);
    expect(original?.hasReceivedResults).toBe(false);
    unregister();
    unregister();
    expect(useWorkspaceStore.getState().surfaces["generate.results"]).toBeUndefined();
  });

  it("a stale unregister after a re-register and patch is a no-op", () => {
    const first = useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready });
    const second = useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready, readiness: "hydrating" });
    useWorkspaceStore.getState().updateSurface("history.detail", { hasEditableState: true });
    first();
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toEqual({
      id: "history.detail", ...ready, readiness: "hydrating", hasEditableState: true,
    });
    second();
    expect(useWorkspaceStore.getState().surfaces).toEqual({});
  });

  it("updateSurface on an unregistered id is a no-op", () => {
    const state = useWorkspaceStore.getState();
    state.updateSurface("history.list", { readiness: "ready" });
    expect(useWorkspaceStore.getState()).toBe(state);
  });
});

describe("operations", () => {
  it.each(["completed", "failed", "aborted", "superseded"] as const)("ends only its own operation once with %s", (outcome) => {
    vi.spyOn(Date, "now").mockReturnValue(1234);
    const handle = useWorkspaceStore.getState().beginOperation("resolve", "generate.form");
    const sibling = useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
    expect(sibling.id).not.toBe(handle.id);
    expect(useWorkspaceStore.getState().operations[0]).toEqual({
      id: handle.id, kind: "resolve", surface: "generate.form", startedAt: 1234,
    });
    handle.end(outcome);
    const state = useWorkspaceStore.getState();
    handle.end("failed");
    expect(useWorkspaceStore.getState()).toBe(state);
    expect(state.operations.map((op) => op.id)).toEqual([sibling.id]);
    sibling.end("completed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it("observing the store never aborts in-flight work", async () => {
    const controller = new AbortController();
    const abort = vi.spyOn(controller, "abort");
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", (_input: RequestInfo, init: RequestInit) => new Promise<Response>((resolve, reject) => {
      finish = resolve;
      init.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }));
    const request = fetch("/api/generate", { signal: controller.signal });
    const handle = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    const unsubscribe = useWorkspaceStore.subscribe((state) => isRefreshSafe(state));
    isRefreshSafe(useWorkspaceStore.getState());
    useWorkspaceStore.getState().registerSurface({ id: "generate.results", ...ready });
    expect(useWorkspaceStore.getState().operations[0]).not.toHaveProperty("controller");
    unsubscribe();
    expect(abort).not.toHaveBeenCalled();
    expect(controller.signal.aborted).toBe(false);
    const response = new Response("done");
    finish(response);
    await expect(request).resolves.toBe(response);
    handle.end("completed");
  });
});

describe("isRefreshSafe", () => {
  it("is unsafe with no registered surface", () => {
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: false, blockers: [{ kind: "no_surface" }] });
  });

  it("is safe with ready, empty surfaces and no operations", () => {
    useWorkspaceStore.getState().registerSurface({ id: "history.list", ...ready });
    useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready });
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: true, blockers: [] });
  });

  it.each<{ kind: string; patch: Partial<SurfaceParticipation> }>([
    { kind: "hydrating", patch: { readiness: "hydrating" } },
    { kind: "restoring", patch: { readiness: "restoring" } },
    { kind: "editable", patch: { hasEditableState: true } },
    { kind: "results", patch: { hasReceivedResults: true } },
  ])("reports $kind as a blocker", ({ kind, patch }) => {
    useWorkspaceStore.getState().registerSurface({ id: "generate.form", ...ready, ...patch });
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: false, blockers: [{ kind, surface: "generate.form" }] });
  });

  it("lists every blocker in registration order, readiness before editable before results, then operations", () => {
    useWorkspaceStore.getState().registerSurface({ id: "generate.results", ...ready, hasReceivedResults: true });
    useWorkspaceStore.getState().registerSurface({ id: "generate.form", readiness: "restoring", hasEditableState: true, hasReceivedResults: true });
    useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
    expect(isRefreshSafe(useWorkspaceStore.getState()).blockers).toEqual([
      { kind: "results", surface: "generate.results" },
      { kind: "restoring", surface: "generate.form" },
      { kind: "editable", surface: "generate.form" },
      { kind: "results", surface: "generate.form" },
      { kind: "operation", operation: "prompt_preview", surface: "generate.confirmation" },
    ]);
  });

  it("reports operations even with no registered surfaces", () => {
    useWorkspaceStore.getState().beginOperation("export_odt", "generate.results");
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: false, blockers: [
      { kind: "no_surface" },
      { kind: "operation", operation: "export_odt", surface: "generate.results" },
    ] });
  });
});

it("resets participation and operations without letting stale cleanup remove new work", () => {
  const unregister = useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready });
  const oldHandle = useWorkspaceStore.getState().beginOperation("modification", "history.modification");
  resetWorkspaceStoreForTests();
  expect(useWorkspaceStore.getState().surfaces).toEqual({});
  expect(useWorkspaceStore.getState().operations).toEqual([]);
  useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready });
  const handle = useWorkspaceStore.getState().beginOperation("modification", "history.modification");
  unregister();
  oldHandle.end("aborted");
  expect(useWorkspaceStore.getState().surfaces["history.detail"]).toBeDefined();
  expect(useWorkspaceStore.getState().operations.map((op) => op.id)).toEqual([handle.id]);
});
