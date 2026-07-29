/**
 * LoginPage — signout reason banner (issue #243)
 *
 * When a user is redirected to the login page because their session could not
 * continue (expired or reached the 30-day hard cap), LoginPage reads the
 * exam_signout_reason flag from localStorage, determines whether an unfinished
 * draft exists in this browser, and shows an appropriate banner above the form.
 *
 * With draft:    cause sentence + in-this-browser sentence
 * Without draft: cause sentence + generic "sign in to continue" sentence
 * No flag:       no banner at all
 *
 * The flag is consumed (cleared) on the first render so it doesn't reappear on
 * subsequent page visits.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Module mocks ─────────────────────────────────────────────────────────────

const sendMagicLinkMock = vi.hoisted(() => vi.fn());
const loadDraftMock = vi.hoisted(() =>
  vi.fn<[string], import("../lib/formDraft").FormDraft | null>(),
);

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: () => false,
    sendMagicLink: sendMagicLinkMock,
    logout: vi.fn(),
  }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../components/LanguageSwitcher", () => ({
  default: () => null,
}));

// Mock formDraft so we can control whether a draft exists.
vi.mock("../lib/formDraft", () => ({
  loadDraft: loadDraftMock,
  saveDraft: vi.fn(),
  clearDraft: vi.fn(),
}));

import LoginPage from "./LoginPage";

// ── Helpers ──────────────────────────────────────────────────────────────────

function writeSignoutReason(reason: "session_expired" | "30day_limit", userId = "u1") {
  localStorage.setItem(
    "exam_signout_reason",
    JSON.stringify({ reason, userId }),
  );
}

function renderLogin() {
  render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("LoginPage — signout reason banner", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    loadDraftMock.mockReturnValue(null);
  });

  afterEach(() => {
    cleanup();
  });

  it("shows no banner when no signout reason flag is present", () => {
    renderLogin();
    expect(screen.queryByTestId("signout-banner")).not.toBeInTheDocument();
  });

  // ── session_expired ────────────────────────────────────────────────────────

  it("shows the expired-session cause message without draft notice when no draft exists", async () => {
    writeSignoutReason("session_expired");
    loadDraftMock.mockReturnValue(null);

    renderLogin();

    const banner = await screen.findByTestId("signout-banner");
    expect(banner).toHaveTextContent("login.signout.reason_expired");
    expect(banner).toHaveTextContent("login.signout.next_step");
    expect(banner).not.toHaveTextContent("login.signout.draft_notice");
    // 30-day-limit cause text must not appear
    expect(banner).not.toHaveTextContent("login.signout.reason_30day_limit");
  });

  it("shows the expired-session cause message WITH draft notice when a draft exists", async () => {
    writeSignoutReason("session_expired", "u1");
    loadDraftMock.mockReturnValue({
      savedAt: "2026-01-01T00:00:00Z",
      fields: {} as never,
    });

    renderLogin();

    const banner = await screen.findByTestId("signout-banner");
    expect(banner).toHaveTextContent("login.signout.reason_expired");
    expect(banner).toHaveTextContent("login.signout.draft_notice");
    expect(banner).not.toHaveTextContent("login.signout.next_step");
  });

  // ── 30day_limit ────────────────────────────────────────────────────────────

  it("shows the 30-day-limit cause message without draft notice when no draft exists", async () => {
    writeSignoutReason("30day_limit");
    loadDraftMock.mockReturnValue(null);

    renderLogin();

    const banner = await screen.findByTestId("signout-banner");
    expect(banner).toHaveTextContent("login.signout.reason_30day_limit");
    expect(banner).toHaveTextContent("login.signout.next_step");
    expect(banner).not.toHaveTextContent("login.signout.draft_notice");
    // Expired-session cause text must not appear
    expect(banner).not.toHaveTextContent("login.signout.reason_expired");
  });

  it("shows the 30-day-limit cause message WITH draft notice when a draft exists", async () => {
    writeSignoutReason("30day_limit", "u2");
    loadDraftMock.mockReturnValue({
      savedAt: "2026-01-01T00:00:00Z",
      fields: {} as never,
    });

    renderLogin();

    const banner = await screen.findByTestId("signout-banner");
    expect(banner).toHaveTextContent("login.signout.reason_30day_limit");
    expect(banner).toHaveTextContent("login.signout.draft_notice");
    expect(banner).not.toHaveTextContent("login.signout.next_step");
  });

  // ── loadDraft is called with the correct userId ────────────────────────────

  it("calls loadDraft with the userId stored in the signout reason data", async () => {
    writeSignoutReason("session_expired", "specific-user-abc");

    renderLogin();

    await waitFor(() => {
      expect(loadDraftMock).toHaveBeenCalledWith("specific-user-abc");
    });
  });

  // ── The flag is consumed (cleared) on first render ─────────────────────────

  it("clears the signout reason flag from localStorage after reading it", async () => {
    writeSignoutReason("session_expired");

    renderLogin();

    await screen.findByTestId("signout-banner");
    expect(localStorage.getItem("exam_signout_reason")).toBeNull();
  });
});
