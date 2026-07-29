/**
 * Tests for the sign-out-on-401 path in renewSessionIfNeeded (issue #243).
 *
 * When the backend refuses either:
 *   a) GET /auth/me   → 401 (session truly expired)
 *   b) POST /auth/refresh → 401 (hard 30-day cap hit)
 *
 * the function must:
 *   1. Save the signout reason + userId to localStorage (exam_signout_reason)
 *      so LoginPage can show the cause-specific banner.
 *   2. Save the current pathname to localStorage (exam_return_to) only when
 *      it is one of the allowed 出題 form routes (/generate/math etc.).
 *      Non-form paths (e.g. /history) are silently skipped for the destination.
 *
 * Network errors and non-401 HTTP failures must still be swallowed by the
 * caller's .catch(() => undefined) — no signout state is written.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.hoisted(() => vi.fn());
const getMeMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    apiFetch: apiFetchMock,
    getMe: getMeMock,
  };
});

import { ApiError } from "../api/client";
import { renewSessionIfNeeded } from "./sessionRenewal";
import { useAuthStore } from "../store/authStore";

const AUTH_USER = {
  id: "teacher-1",
  email: "teacher@example.com",
  created_at: "2026-01-01T00:00:00Z",
};

const NEAR_EXPIRY = "2026-08-01T12:00:00Z"; // 1 day — within 2-day threshold

function meResponse(sessionExpiresAt: string) {
  return {
    ...AUTH_USER,
    session_expires_at: sessionExpiresAt,
    renewal_threshold_days: 2,
    server_time: "2026-07-31T12:00:00Z",
  };
}

function signIn(): void {
  useAuthStore.getState().login("old-token", AUTH_USER);
}

describe("renewSessionIfNeeded — sign-out-on-401 behavior", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    getMeMock.mockReset();
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    // Navigate to a valid 出題 form route so the return destination is saved.
    window.history.pushState({}, "", "/generate/math");
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
  });

  // ── GET /auth/me → 401 (expired session) ───────────────────────────────────

  it("saves session_expired reason and /generate/math destination when getMe 401s", async () => {
    signIn();
    getMeMock.mockRejectedValueOnce(new ApiError(401, "Token expired"));

    await renewSessionIfNeeded().catch(() => undefined);

    const rawReason = localStorage.getItem("exam_signout_reason");
    expect(rawReason).not.toBeNull();
    const { reason, userId } = JSON.parse(rawReason!) as {
      reason: string;
      userId: string;
    };
    expect(reason).toBe("session_expired");
    expect(userId).toBe("teacher-1");

    expect(localStorage.getItem("exam_return_to")).toBe("/generate/math");
  });

  it("saves session_expired reason for each allowed 出題 route", async () => {
    for (const path of [
      "/generate/social_studies",
      "/generate/natural_sciences",
    ]) {
      localStorage.clear();
      useAuthStore.setState({ token: null, user: null });
      signIn();
      getMeMock.mockRejectedValueOnce(new ApiError(401, "Token expired"));
      window.history.pushState({}, "", path);

      await renewSessionIfNeeded().catch(() => undefined);

      expect(localStorage.getItem("exam_return_to")).toBe(path);
      const rawReason = localStorage.getItem("exam_signout_reason");
      const { reason } = JSON.parse(rawReason!) as { reason: string };
      expect(reason).toBe("session_expired");
    }
  });

  it("saves signout reason but NOT return destination when path is not an 出題 route", async () => {
    window.history.pushState({}, "", "/history");
    signIn();
    getMeMock.mockRejectedValueOnce(new ApiError(401, "Token expired"));

    await renewSessionIfNeeded().catch(() => undefined);

    const rawReason = localStorage.getItem("exam_signout_reason");
    expect(rawReason).not.toBeNull();
    const { reason } = JSON.parse(rawReason!) as { reason: string };
    expect(reason).toBe("session_expired");
    // /history is not in the allowlist → no return destination saved
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  // ── POST /auth/refresh → 401 (30-day cap) ──────────────────────────────────

  it("saves 30day_limit reason and return destination when refresh 401s", async () => {
    signIn();
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));
    apiFetchMock.mockRejectedValueOnce(
      new ApiError(401, "Session past 30-day cap"),
    );

    await renewSessionIfNeeded().catch(() => undefined);

    const rawReason = localStorage.getItem("exam_signout_reason");
    expect(rawReason).not.toBeNull();
    const { reason, userId } = JSON.parse(rawReason!) as {
      reason: string;
      userId: string;
    };
    expect(reason).toBe("30day_limit");
    expect(userId).toBe("teacher-1");

    expect(localStorage.getItem("exam_return_to")).toBe("/generate/math");
  });

  // ── Network / non-401 errors → still swallowed, no signout state ───────────

  it("does NOT save signout state when refresh fails with a network error (non-ApiError)", async () => {
    signIn();
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));
    apiFetchMock.mockRejectedValueOnce(new Error("Network error"));

    await renewSessionIfNeeded().catch(() => undefined);

    expect(localStorage.getItem("exam_signout_reason")).toBeNull();
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  it("does NOT save signout state when refresh fails with a non-401 ApiError (e.g. 500)", async () => {
    signIn();
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));
    apiFetchMock.mockRejectedValueOnce(new ApiError(500, "Server error"));

    await renewSessionIfNeeded().catch(() => undefined);

    expect(localStorage.getItem("exam_signout_reason")).toBeNull();
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  it("does NOT save signout state when getMe fails with a non-401 error", async () => {
    signIn();
    getMeMock.mockRejectedValueOnce(new Error("Network error"));

    await renewSessionIfNeeded().catch(() => undefined);

    expect(localStorage.getItem("exam_signout_reason")).toBeNull();
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });
});
