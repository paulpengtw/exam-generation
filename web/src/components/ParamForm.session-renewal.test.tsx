import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const apiFetchMock = vi.hoisted(() => vi.fn());
const getMeMock = vi.hoisted(() => vi.fn());
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  apiFetch: apiFetchMock,
  getMe: getMeMock,
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import { useAuthStore } from "../store/authStore";
import ParamForm from "./ParamForm";

const AUTH_USER = {
  id: "teacher-1",
  email: "teacher@example.com",
  created_at: "2026-01-01T00:00:00Z",
};

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

function meResponse(sessionExpiresAt: string) {
  return {
    ...AUTH_USER,
    session_expires_at: sessionExpiresAt,
    renewal_threshold_minutes: 360,
    server_time: "2026-07-31T12:00:00Z",
  };
}

function signIn(): void {
  useAuthStore.getState().login("old-token", AUTH_USER);
}

function renderForm(): void {
  render(
    <ParamForm subject="math" onSubmit={() => {}} disabled={false} />,
  );
}

describe("ParamForm mount-time session renewal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    getMeMock.mockResolvedValue(meResponse("2026-07-31T15:00:00Z"));
    apiFetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "fresh-token",
          token_type: "bearer",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("refreshes once within the threshold and persists the returned token", async () => {
    signIn();

    renderForm();

    await waitFor(() => {
      expect(useAuthStore.getState().token).toBe("fresh-token");
    });
    expect(getMeMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith("/auth/refresh", {
      method: "POST",
    });
    expect(localStorage.getItem("auth_token")).toBe("fresh-token");
  });

  it("does not refresh when the server reports plenty of time remaining", async () => {
    signIn();
    getMeMock.mockResolvedValueOnce(meResponse("2026-08-10T12:00:00Z"));

    renderForm();

    await waitFor(() => {
      expect(getMeMock).toHaveBeenCalledTimes(1);
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe("old-token");
  });

  it("swallows a 401 refresh refusal and leaves the form usable", async () => {
    signIn();
    apiFetchMock.mockRejectedValueOnce(
      Object.assign(new Error("renewal refused"), { status: 401 }),
    );

    renderForm();

    const generateButton = await screen.findByRole("button", {
      name: "form.btn_generate",
    });
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText("renewal refused")).not.toBeInTheDocument();

    fireEvent.click(generateButton);
    expect(
      await screen.findByRole("button", { name: "form.btn_confirm_send" }),
    ).toBeInTheDocument();
  });

  it("does not schedule a later renewal after its one mount-time check", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2099-12-31T23:59:59Z"));
    signIn();

    renderForm();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      vi.advanceTimersByTime(365 * 24 * 60 * 60 * 1_000);
      await Promise.resolve();
    });
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not inspect the session when mounted unauthenticated", async () => {
    renderForm();

    await screen.findByRole("button", { name: "form.btn_generate" });
    expect(getMeMock).not.toHaveBeenCalled();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
