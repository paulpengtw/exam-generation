import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitModificationBatch, type ModificationBatchRequest } from "../api/client";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { useModificationRun } from "./useModificationRun";

vi.mock("../api/client", () => ({ submitModificationBatch: vi.fn() }));
const fetchEventSourceMock = vi.hoisted(() => vi.fn<(url: string, init: FetchEventSourceInit) => Promise<void>>());
vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: fetchEventSourceMock }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const batch: ModificationBatchRequest = { annotations: [] };
const completedResult = {
  record_id: "replacement", question: { id: "q1", 題目: ["changed"] },
  ripple_report: [], verified: true, verification: null, failure_details: null,
};
const beginOperation = useWorkspaceStore.getState().beginOperation;
let end: ReturnType<typeof vi.fn>;

function stream() {
  return fetchEventSourceMock.mock.lastCall![1];
}
function event(name: string, data: unknown = {}) {
  act(() => { stream().onmessage?.({ id: "", event: name, data: JSON.stringify(data) }); });
}

beforeEach(() => {
  resetWorkspaceStoreForTests();
  vi.mocked(submitModificationBatch).mockReset().mockResolvedValue({ run_id: "run-1", status: "accepted" });
  fetchEventSourceMock.mockReset().mockResolvedValue(undefined);
  end = vi.fn();
  vi.spyOn(useWorkspaceStore.getState(), "beginOperation").mockImplementation((...args) => {
    const op = beginOperation(...args);
    return { id: op.id, end: (outcome) => { end(outcome); op.end(outcome); } };
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  useWorkspaceStore.setState({ beginOperation });
});

describe("modification admission", () => {
  it("is submitting until the POST returns a run id, with an operation covering both phases", async () => {
    const pending = deferred<Awaited<ReturnType<typeof submitModificationBatch>>>();
    vi.mocked(submitModificationBatch).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useModificationRun("record-1"));
    expect(result.current.admission).toBe("idle");
    expect(result.current.admissionError).toBeNull();
    act(() => { void result.current.start(batch); });
    expect(result.current.admission).toBe("submitting");
    expect(result.current.status).toBe("running");
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ kind: "modification", surface: "history.modification" }),
    ]);
    await act(async () => { pending.resolve({ run_id: "run-1", status: "accepted" }); });
    expect(result.current.admission).toBe("admitted");
    expect(useWorkspaceStore.getState().operations).toHaveLength(1);
    event("done", completedResult);
    expect(result.current.status).toBe("completed");
    expect(result.current.admission).toBe("admitted");
    expect(result.current.result?.record_id).toBe("replacement");
    expect(end).toHaveBeenCalledWith("completed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it.each(["rejection", "missing id"])("rejects admission for %s with the existing error", async (failure) => {
    const message = failure === "rejection" ? "not_latest_version" : "Modification admission did not return a run id";
    if (failure === "rejection") vi.mocked(submitModificationBatch).mockRejectedValue(new Error(message));
    else vi.mocked(submitModificationBatch).mockResolvedValue({ run_id: "", status: "accepted" });
    const { result } = renderHook(() => useModificationRun("record-1"));
    await act(async () => { await result.current.start(batch); });
    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toBe(message);
    expect(result.current.error).toEqual(new Error(message));
    expect(result.current.status).toBe("error");
    expect(end).toHaveBeenCalledWith("failed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
    vi.mocked(submitModificationBatch).mockResolvedValue({ run_id: "retry", status: "accepted" });
    await act(async () => { await result.current.start(batch); });
    expect(result.current.admission).toBe("admitted");
    expect(result.current.admissionError).toBeNull();
  });

  it.each(["error", "onerror", "throw", "empty done"])("keeps admission after a stream %s", async (failure) => {
    if (failure === "throw") fetchEventSourceMock.mockRejectedValue(new Error("connection lost"));
    const { result } = renderHook(() => useModificationRun("record-1"));
    await act(async () => { await result.current.start(batch); });
    if (failure === "error") event("error", { message: "connection lost" });
    if (failure === "empty done") event("done");
    if (failure === "onerror") act(() => { expect(() => stream().onerror?.(new Error("connection lost"))).toThrow(); });
    expect(result.current.admission).toBe("admitted");
    expect(result.current.admissionError).toBeNull();
    expect(result.current.status).toBe("error");
    expect(end).toHaveBeenCalledWith("failed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it("does nothing without a record id", async () => {
    const { result } = renderHook(() => useModificationRun());
    await act(async () => { await result.current.start(batch); });
    expect(result.current.admission).toBe("idle");
    expect(result.current.status).toBe("idle");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it.each([false, true])("ends on unmount with admitted=%s and ignores late responses", async (admitted) => {
    const pending = deferred<Awaited<ReturnType<typeof submitModificationBatch>>>();
    if (!admitted) vi.mocked(submitModificationBatch).mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(() => useModificationRun("record-1"));
    await act(async () => { void result.current.start(batch); });
    const before = result.current;
    unmount();
    expect(end).toHaveBeenCalledWith("aborted");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
    await act(async () => { pending.resolve({ run_id: "late", status: "accepted" }); });
    expect(result.current).toBe(before);
  });

  it("supersedes a pending POST without allowing it to settle the new admission", async () => {
    const pending = deferred<Awaited<ReturnType<typeof submitModificationBatch>>>();
    vi.mocked(submitModificationBatch).mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useModificationRun("record-1"));
    act(() => { void result.current.start(batch); });
    await act(async () => { await result.current.start(batch); });
    expect(end).toHaveBeenCalledWith("superseded");
    await act(async () => { pending.reject(new Error("old rejection")); });
    expect(result.current.admission).toBe("admitted");
    expect(result.current.admissionError).toBeNull();
    expect(result.current.status).toBe("running");
    expect(useWorkspaceStore.getState().operations).toHaveLength(1);
  });
});
