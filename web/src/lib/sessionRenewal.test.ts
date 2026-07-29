import { afterEach, describe, expect, it, vi } from "vitest";

import { shouldRenew } from "./sessionRenewal";

describe("shouldRenew", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns true when the server-reported remaining time is below the threshold", () => {
    expect(
      shouldRenew({
        session_expires_at: "2026-07-31T17:59:59Z",
        renewal_threshold_minutes: 360,
        server_time: "2026-07-31T12:00:00Z",
      }),
    ).toBe(true);
  });

  it("returns false when the server-reported remaining time is above the threshold", () => {
    expect(
      shouldRenew({
        session_expires_at: "2026-07-31T18:00:01Z",
        renewal_threshold_minutes: 360,
        server_time: "2026-07-31T12:00:00Z",
      }),
    ).toBe(false);
  });

  it("returns false when the remaining time is exactly the threshold", () => {
    expect(
      shouldRenew({
        session_expires_at: "2026-07-31T18:00:00Z",
        renewal_threshold_minutes: 360,
        server_time: "2026-07-31T12:00:00Z",
      }),
    ).toBe(false);
  });

  it("ignores an absurd device clock and uses only the server-provided timestamps", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2099-12-31T23:59:59Z"));
    const dateNowSpy = vi.spyOn(Date, "now");

    expect(
      shouldRenew({
        session_expires_at: "2026-07-31T14:00:00Z",
        renewal_threshold_minutes: 360,
        server_time: "2026-07-31T12:00:00Z",
      }),
    ).toBe(true);
    expect(dateNowSpy).not.toHaveBeenCalled();
  });
});
