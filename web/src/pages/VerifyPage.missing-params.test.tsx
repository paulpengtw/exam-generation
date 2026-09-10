/**
 * VerifyPage — missing token/email query params (issue #690)
 *
 * When the user arrives at /verify without the required token and/or email
 * query parameters, the page must immediately show the error state (the
 * role="alert" paragraph) and must not navigate away.
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

function renderVerifyNoParams() {
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
    ],
    { initialEntries: ["/verify"] },
  );
  render(<RouterProvider router={router} />);
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("VerifyPage — missing token/email params", () => {
  beforeEach(() => {
    verifyTokenMock.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the error alert when token and email are missing from the URL", async () => {
    renderVerifyNoParams();
    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("verify.error_default");
  });

  it("does not navigate to /generate when params are missing", async () => {
    renderVerifyNoParams();
    await screen.findByRole("alert");
    expect(screen.queryByTestId("page-generate-default")).not.toBeInTheDocument();
  });

  it("does not call verifyToken when params are missing", async () => {
    renderVerifyNoParams();
    await screen.findByRole("alert");
    expect(verifyTokenMock).not.toHaveBeenCalled();
  });
});
