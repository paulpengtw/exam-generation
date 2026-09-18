/**
 * useGenerate stream 401 (onopen) — recovery snapshot preservation.
 *
 * Issue #776: A stream 401 in useGenerate must:
 *   (a) preserve the recovery snapshot (logout(), not logoutExplicit()),
 *   (b) store "session_expired" as the signout reason, and
 *   (c) never call logoutExplicit() (which would delete the snapshot).
 *
 * This test uses the REAL useGenerate hook and mocks only the transport
 * layer (fetchEventSource), triggering onopen with an HTTP 401 response.
 * The companion file recoveryFlow.test.tsx covered this path tautologically
 * (calling saveSignoutReason + logout() directly); this file proves the
 * real code path.
 */
import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchEventSourceMock = vi.hoisted(() =>
  vi
    .fn<
      (
        input: RequestInfo,
        init: FetchEventSourceInit,
      ) => Promise<void>
    >()
    .mockResolvedValue(undefined),
);

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

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

const TEST_USER = {
  id: "u401-hook-test",
  email: "u401@test.com",
  created_at: "2024-01-01T00:00:00Z",
};

beforeEach(() => {
  fetchEventSourceMock.mockClear();
  useAuthStore.setState({ token: "tok", user: TEST_USER });
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  // Re-stub after restoreAllMocks
  useAuthStore.setState({ token: "tok", user: TEST_USER });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function latestStreamOptions(): FetchEventSourceInit {
  const call = fetchEventSourceMock.mock.lastCall;
  if (!call) throw new Error("Expected generate() to open an event stream");
  return call[1];
}

describe("useGenerate — stream 401 (onopen) preserves recovery snapshot (#776)", () => {
  it("onopen 401 saves session_expired reason, calls logout() but NOT logoutExplicit(), leaves snapshot intact", async () => {
    // Arrange: create a sparse snapshot (no passage key) — same shape that seedSnapshot()
    // produces in recoveryFlow.test.tsx — to prove the real code path handles it.
    const snapshotId = "gen-401-snap";
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

    // Confirm snapshot is present before the 401
    expect(loadSnapshot(TEST_USER.id, snapshotId)).not.toBeNull();

    // Spy on logoutExplicit — the 401 path must NOT call it
    const logoutExplicitSpy = vi.spyOn(useAuthStore.getState(), "logoutExplicit");

    // Render the real hook and start a generate run
    const { result } = renderHook(() => useGenerate());
    act(() => {
      result.current.generate({ subject: "math", count: 1 });
    });

    // Trigger the real onopen handler with a 401 response
    await act(async () => {
      try {
        await latestStreamOptions().onopen?.(
          new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
        );
      } catch {
        // FatalStreamError is expected — fetchEventSource stops retrying on this throw.
      }
    });

    // (a) Snapshot survives: logout() does NOT delete snapshots; logoutExplicit() would.
    expect(loadSnapshot(TEST_USER.id, snapshotId)).not.toBeNull();

    // (b) Signout reason is stored as "session_expired" so the login page shows
    // the correct banner and can navigate back after re-authentication.
    const rawReason = localStorage.getItem("exam_signout_reason");
    expect(rawReason).not.toBeNull();
    expect((JSON.parse(rawReason!) as Record<string, unknown>).reason).toBe(
      "session_expired",
    );

    // (c) logoutExplicit was NOT called — only the credential-clearing logout() was used.
    expect(logoutExplicitSpy).not.toHaveBeenCalled();
  });
});
