/**
 * Verifies that ReleaseNotice is mounted in RootLayout and therefore
 * present on all routed pages.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useReleaseStore } from "../lib/release/releaseStore";
import { resetReleaseDetector } from "../lib/release/releaseStore";

// Stub build globals
vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

// Prevent actual fetch calls from the useReleaseStatus hook
vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));

// Mock heavy page components
vi.mock("./StagingBanner", () => ({ default: () => null }));
vi.mock("./FeedbackButton", () => ({ default: () => null }));
vi.mock("react-router-dom", () => ({
  Outlet: () => <div data-testid="outlet" />,
}));

import RootLayout from "./RootLayout";

beforeEach(() => {
  vi.useFakeTimers();
  resetReleaseDetector();
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
  });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("RootLayout release notice", () => {
  it("renders a status or alert element for the release notice", () => {
    render(<RootLayout />);
    // Either role=status (checking/current) or role=alert (update/paused)
    const notice =
      screen.queryByRole("status") ?? screen.queryByRole("alert");
    expect(notice).toBeInTheDocument();
  });

  it("notice reflects update-required after store update", async () => {
    const { rerender } = render(<RootLayout />);

    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      lastCheckedAt: Date.now(),
      lastFailure: null,
    });

    // Re-render to pick up the store change
    rerender(<RootLayout />);

    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
  });
});
