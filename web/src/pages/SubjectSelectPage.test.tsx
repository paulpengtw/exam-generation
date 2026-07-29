import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const navigateMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (
    selector: (state: {
      user: { email: string };
      logout: () => void;
    }) => unknown,
  ) =>
    selector({
      user: { email: "teacher@example.com" },
      logout: logoutMock,
    }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import SubjectSelectPage from "./SubjectSelectPage";

function renderPage() {
  return render(<SubjectSelectPage />);
}

function clickLogout() {
  fireEvent.click(
    screen.getByRole("button", { name: "generate.btn_logout" }),
  );
}

describe("SubjectSelectPage logout confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks for confirmation before logging out", () => {
    renderPage();

    clickLogout();

    expect(screen.getByText("confirm.logout_title")).toBeInTheDocument();
    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("mentions only the session, since this page has nothing else to lose", () => {
    renderPage();

    clickLogout();

    expect(
      screen.getByText("confirm.logout_body_session"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("confirm.logout_body_work_lost"),
    ).not.toBeInTheDocument();
  });

  it("cancelling does not log out and does not navigate", () => {
    renderPage();
    clickLogout();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.destructive_cancel" }),
    );

    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
    expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
  });

  it("confirming logs out and returns to the login page", () => {
    renderPage();
    clickLogout();

    fireEvent.click(
      screen.getByRole("button", { name: "confirm.logout_confirm" }),
    );

    expect(logoutMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("Esc cancels the logout", () => {
    renderPage();
    clickLogout();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
    expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
  });

  it("still navigates normally to a subject", () => {
    renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /subject_select\.math_title/ }),
    );

    expect(navigateMock).toHaveBeenCalledOnce();
    expect(navigateMock).toHaveBeenCalledWith("/generate/math");
    expect(screen.queryByText("confirm.logout_title")).not.toBeInTheDocument();
    expect(logoutMock).not.toHaveBeenCalled();
  });
});
