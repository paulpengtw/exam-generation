/**
 * VerifyPage — post-login return destination (issue #243)
 *
 * After a successful magic-link verification, the user should be navigated to:
 *   • The path stored in exam_return_to (localStorage) if it passes the
 *     allowlist check (one of the three 出題 form routes), OR
 *   • The default /generate route when no valid destination is stored.
 *
 * The stored value is consumed (cleared) in both cases.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Module mocks ─────────────────────────────────────────────────────────────

const verifyTokenMock = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    verifyToken: verifyTokenMock,
    isAuthenticated: () => false,
    sendMagicLink: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import VerifyPage from "./VerifyPage";

// ── Helpers ──────────────────────────────────────────────────────────────────

function renderVerify(token = "abc", email = "test@example.com") {
  const router = createMemoryRouter(
    [
      {
        path: "/verify",
        element: <VerifyPage />,
      },
      {
        path: "/generate",
        element: <div data-testid="page-generate-default" />,
      },
      {
        path: "/generate/math",
        element: <div data-testid="page-generate-math" />,
      },
      {
        path: "/generate/social_studies",
        element: <div data-testid="page-generate-social_studies" />,
      },
      {
        path: "/generate/natural_sciences",
        element: <div data-testid="page-generate-natural_sciences" />,
      },
    ],
    { initialEntries: [`/verify?token=${token}&email=${encodeURIComponent(email)}`] },
  );
  render(<RouterProvider router={router} />);
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("VerifyPage — post-login return destination", () => {
  beforeEach(() => {
    verifyTokenMock.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("navigates to /generate (default) when no return destination is stored", async () => {
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-default");
  });

  it("navigates to /generate/math when that destination is stored", async () => {
    localStorage.setItem("exam_return_to", "/generate/math");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-math");
    // The destination is consumed (cleared) after use
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  it("navigates to /generate/social_studies when stored", async () => {
    localStorage.setItem("exam_return_to", "/generate/social_studies");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-social_studies");
  });

  it("navigates to /generate/natural_sciences when stored", async () => {
    localStorage.setItem("exam_return_to", "/generate/natural_sciences");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-natural_sciences");
  });

  it("falls back to /generate for an external URL in exam_return_to", async () => {
    localStorage.setItem("exam_return_to", "https://evil.example");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-default");
    // Invalid value is still cleared
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  it("falls back to /generate for /history (not in allowlist)", async () => {
    localStorage.setItem("exam_return_to", "/history");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-default");
  });

  it("falls back to /generate for /generate (bare subject picker — not a form route)", async () => {
    localStorage.setItem("exam_return_to", "/generate");
    verifyTokenMock.mockResolvedValueOnce({ success: true });
    renderVerify();
    await screen.findByTestId("page-generate-default");
  });

  it("remains on /verify error state when verification fails", async () => {
    verifyTokenMock.mockResolvedValueOnce({ success: false });
    renderVerify();
    await screen.findByRole("alert");
    // No navigation to generate pages
    expect(screen.queryByTestId("page-generate-default")).not.toBeInTheDocument();
    expect(screen.queryByTestId("page-generate-math")).not.toBeInTheDocument();
  });
});
