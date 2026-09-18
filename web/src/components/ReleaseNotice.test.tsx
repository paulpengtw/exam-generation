import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useReleaseStore } from "../lib/release/releaseStore";
import { useLangStore } from "../store/langStore";
import ReleaseNotice from "./ReleaseNotice";

// Stub build globals
vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

function setStatus(
  status: "checking" | "current" | "update-required" | "paused" | "unavailable",
  requiredBuildId: string | null = null,
) {
  useReleaseStore.setState({
    status,
    requiredBuildId,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
  });
}

beforeEach(() => {
  useLangStore.setState({ lang: "en-US" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.stubGlobal("__BUILD_ID__", "build-A");
  vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
});

describe("ReleaseNotice", () => {
  it("checking state uses role=status aria-live=polite", () => {
    setStatus("checking");
    render(<ReleaseNotice />);
    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("aria-live", "polite");
    expect(notice).toHaveTextContent(/checking/i);
  });

  it("current state uses role=status and stays in the DOM (may be sr-only)", () => {
    setStatus("current");
    render(<ReleaseNotice />);
    // Must remain in DOM for assistive tech
    const notice = screen.getByRole("status");
    expect(notice).toBeInTheDocument();
  });

  it("update-required state uses role=alert", () => {
    setStatus("update-required", "build-B");
    render(<ReleaseNotice />);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent(/update/i);
    expect(alert).toHaveTextContent(/work is kept/i);
  });

  it("paused state uses role=alert", () => {
    setStatus("paused");
    render(<ReleaseNotice />);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent(/update in progress/i);
  });

  it("unavailable state uses role=status", () => {
    setStatus("unavailable");
    render(<ReleaseNotice />);
    const notice = screen.getByRole("status");
    expect(notice).toBeInTheDocument();
    expect(notice).toHaveTextContent(/cannot check/i);
  });

  it("check-again button is keyboard operable (click)", async () => {
    const user = userEvent.setup({ delay: null });
    setStatus("unavailable");

    // Mock checkNow
    const checkNowMock = vi.fn().mockResolvedValue(undefined);
    useReleaseStore.setState({ checkNow: checkNowMock } as never);

    render(<ReleaseNotice />);

    const btn = screen.getByRole("button", { name: /check again/i });
    await user.click(btn);
    expect(checkNowMock).toHaveBeenCalledTimes(1);
  });

  it("check-again button is present in update-required state", () => {
    setStatus("update-required", "build-B");
    render(<ReleaseNotice />);
    expect(screen.getByRole("button", { name: /check again/i })).toBeInTheDocument();
  });

  it("check-again button is present in paused state", () => {
    setStatus("paused");
    render(<ReleaseNotice />);
    expect(screen.getByRole("button", { name: /check again/i })).toBeInTheDocument();
  });

  it("focus is not moved by state changes", async () => {
    setStatus("checking");
    const { rerender } = render(
      <>
        <button>focus-target</button>
        <ReleaseNotice />
      </>,
    );

    const focusTarget = screen.getByRole("button", { name: "focus-target" });
    focusTarget.focus();
    expect(document.activeElement).toBe(focusTarget);

    // Transition to update-required
    setStatus("update-required", "build-B");
    rerender(
      <>
        <button>focus-target</button>
        <ReleaseNotice />
      </>,
    );

    // Focus must remain on the original element
    expect(document.activeElement).toBe(focusTarget);
  });

  it("reduced-motion: no animation classes when prefers-reduced-motion matches", () => {
    // jsdom doesn't implement matchMedia — install a stub
    Object.defineProperty(window, "matchMedia", {
      value: vi.fn().mockReturnValue({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
      configurable: true,
      writable: true,
    });

    setStatus("update-required", "build-B");
    render(<ReleaseNotice />);

    const alert = screen.getByRole("alert");
    // Should not have animation/transition classes
    expect(alert.className).not.toMatch(/transition|animate/);
  });

  it("zh-TW locale renders Chinese text", () => {
    useLangStore.setState({ lang: "zh-TW" });
    setStatus("update-required", "build-B");
    render(<ReleaseNotice />);
    expect(screen.getByRole("alert")).toHaveTextContent(/更新/);
  });

  it("locale switch re-renders the label", () => {
    setStatus("unavailable");
    const { rerender } = render(<ReleaseNotice />);
    expect(screen.getByRole("status")).toHaveTextContent(/cannot check/i);

    useLangStore.setState({ lang: "zh-TW" });
    rerender(<ReleaseNotice />);
    expect(screen.getByRole("status")).toHaveTextContent(/無法檢查/);
  });

  it("chrome text has sentry-unmask class", () => {
    setStatus("current");
    render(<ReleaseNotice />);
    const notice = screen.getByRole("status");
    expect(notice.querySelector(".sentry-unmask")).toBeInTheDocument();
  });
});
