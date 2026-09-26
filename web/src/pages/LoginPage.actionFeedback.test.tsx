import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendMagicLinkMock = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: () => false,
    sendMagicLink: sendMagicLinkMock,
  }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => ({
    "login.title": "Sign in",
    "login.email_label": "Email",
    "login.email_placeholder": "you@example.com",
    "login.validation_email": "Please enter a valid email address.",
    "login.btn_send": "Send magic link",
    "login.btn_sending": "Sending…",
    "login.sent": "Check your email for a login link.",
    "login.error_default": "Failed to send magic link.",
    "action.failed": "Failed",
    "action.retry": "Retry",
    "action.dismiss": "Dismiss",
  }[key] ?? key),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../lib/formDraft", () => ({ loadDraft: () => null }));
vi.mock("../lib/signoutReason", () => ({ consumeSignoutReason: () => null }));

import LoginPage from "./LoginPage";
import { ActionFeedbackProvider } from "../motion/actionFeedback";

function renderLogin() {
  return render(
    <MemoryRouter>
      <ActionFeedbackProvider>
        <LoginPage />
      </ActionFeedbackProvider>
    </MemoryRouter>,
  );
}

describe("LoginPage action feedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the pending status and ignores a second press", async () => {
    let resolve!: (value: { success: boolean }) => void;
    sendMagicLinkMock.mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Email"), "teacher@example.com");
    const button = screen.getByRole("button", { name: "Send magic link" });
    await user.click(button);
    expect(screen.getByRole("status")).toHaveTextContent("Sending…");
    expect(button).toBeDisabled();

    await act(async () => resolve({ success: true }));
    expect(screen.getByRole("status")).toHaveTextContent("Check your email for a login link.");
    expect(sendMagicLinkMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the login label and exposes a failed server detail inline", async () => {
    sendMagicLinkMock.mockResolvedValueOnce({ success: false, error: "Mailbox rejected" });
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Email"), "teacher@example.com");
    await user.click(screen.getByRole("button", { name: "Send magic link" }));

    const button = screen.getByRole("button", { name: "Send magic link" });
    expect(button).toHaveAttribute("data-action-state", "failed");
    expect(button).toHaveTextContent("Send magic link");
    expect(screen.getByRole("alert")).toHaveTextContent("Mailbox rejected");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
