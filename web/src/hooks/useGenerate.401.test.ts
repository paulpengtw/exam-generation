/**
 * useGenerate 401 (on submit or on a run poll) — recovery snapshot preservation.
 *
 * Issue #776: A 401 in useGenerate must:
 *   (a) preserve the recovery snapshot (logout(), not logoutExplicit()),
 *   (b) store "session_expired" as the signout reason, and
 *   (c) never call logoutExplicit() (which would delete the snapshot).
 *
 * These tests use the REAL useGenerate hook and mock only the transport
 * layer (a fake fetch answering the detached-run endpoints, issue #908).
 * The companion file recoveryFlow.test.tsx covered this path tautologically
 * (calling saveSignoutReason + logout() directly); this file proves the
 * real code path.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@sentry/react", () => ({ captureException: vi.fn() }));
vi.mock("../sentry", () => ({ isSentryEnabled: vi.fn().mockReturnValue(false) }));

import { useGenerate } from "./useGenerate";
import { useAuthStore } from "../store/authStore";
import {
  saveSnapshotTransactionally,
  loadSnapshot,
  getOrCreateTabId,
  persistTabPointer,
} from "../lib/recovery/storage";
import { RECOVERY_FORMAT_V1 } from "../lib/recovery/format";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import { runSnapshot, runningQuestion } from "../test/runFixtures";

const TEST_USER = {
  id: "u401-hook-test",
  email: "u401@test.com",
  created_at: "2024-01-01T00:00:00Z",
};

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  server = installFakeRunServer();
  useAuthStore.setState({ token: "tok", user: TEST_USER });
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function seedSnapshot(snapshotId: string) {
  // A sparse snapshot (no passage key) — same shape that seedSnapshot()
  // produces in recoveryFlow.test.tsx — to prove the real code path handles it.
  const tabId = getOrCreateTabId();
  await saveSnapshotTransactionally({
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: snapshotId,
    tab_id: tabId,
    route: "/generate/math",
    subject: "math",
    account_id: TEST_USER.id,
    origin: "https://test.example.com",
    environment: "production",
    source_build_id: "build-A",
    target_build_id: "build-B",
    source_release_revision: 1,
    target_release_revision: 2,
    saved_at: new Date().toISOString(),
    workspace_revision: 0,
    form: {
      kind: "form",
      version: 1,
      // Deliberately sparse (no passage, textInstruction, options, etc.) —
      // the bug fixed in #776 was that passage.trim() crashed on these.
      fields: { topic: "401-test-topic" } as never,
    },
  });
  await persistTabPointer({
    account_id: TEST_USER.id,
    snapshot_id: snapshotId,
    route: "/generate/math",
    tab_id: tabId,
    attempted_target_build_id: "build-B",
    attempted_target_release_revision: 2,
  });
}

function expectSessionExpiredHandled(snapshotId: string, logoutExplicitSpy: ReturnType<typeof vi.spyOn>) {
  // (a) Snapshot survives: logout() does NOT delete snapshots; logoutExplicit() would.
  expect(loadSnapshot(TEST_USER.id, snapshotId)).not.toBeNull();

  // (b) Signout reason is stored as "session_expired" so the login page shows
  // the correct banner and can navigate back after re-authentication.
  const rawReason = localStorage.getItem("exam_signout_reason");
  expect(rawReason).not.toBeNull();
  expect((JSON.parse(rawReason!) as Record<string, unknown>).reason).toBe("session_expired");

  // (c) logoutExplicit was NOT called — only the credential-clearing logout() was used.
  expect(logoutExplicitSpy).not.toHaveBeenCalled();
}

describe("useGenerate — 401 preserves recovery snapshot (#776)", () => {
  it("a 401 on submit saves session_expired reason, calls logout() but NOT logoutExplicit(), leaves snapshot intact", async () => {
    const snapshotId = "gen-401-snap";
    await seedSnapshot(snapshotId);
    expect(loadSnapshot(TEST_USER.id, snapshotId)).not.toBeNull();
    const logoutExplicitSpy = vi.spyOn(useAuthStore.getState(), "logoutExplicit");
    server.failSubmit(401, { detail: "Unauthorized" });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({ subject: "math", count: 1 });
    });
    await flush();

    expect(result.current.status).toBe("error");
    expectSessionExpiredHandled(snapshotId, logoutExplicitSpy);
  });

  it("a 401 on a run poll takes the same path: snapshot kept, session_expired stored, polling stops", async () => {
    const snapshotId = "gen-401-poll-snap";
    await seedSnapshot(snapshotId);
    const logoutExplicitSpy = vi.spyOn(useAuthStore.getState(), "logoutExplicit");
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1")]));

    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({ subject: "math", count: 1 });
    });
    await flush();
    expect(result.current.status).toBe("generating");

    // The session lapses between polls: the run endpoint now answers 401.
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "Unauthorized" }),
      { status: 401 },
    )));
    await flush(3_000);

    expect(result.current.status).toBe("error");
    expectSessionExpiredHandled(snapshotId, logoutExplicitSpy);
    const callsAfterStop = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length;
    await flush(10_000);
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterStop);
  });
});
