import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/**
 * server_time is "2026-07-31T12:00:00Z" and renewal_threshold_minutes is 360.
 * shouldRenew is true when session_expires_at is less than 360 minutes from server_time,
 * i.e. before "2026-07-31T18:00:00Z".
 */
const NEAR_EXPIRY = "2026-07-31T15:00:00Z";    // 3 hours remaining — within threshold
const PLENTY_OF_TIME = "2026-08-10T12:00:00Z"; // 10 days remaining — above threshold

function meResponse(sessionExpiresAt: string) {
  return {
    ...AUTH_USER,
    session_expires_at: sessionExpiresAt,
    renewal_threshold_minutes: 360,
    server_time: "2026-07-31T12:00:00Z",
  };
}

function freshTokenResponse() {
  return new Response(
    JSON.stringify({ access_token: "fresh-token", token_type: "bearer" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function signIn(): void {
  useAuthStore.getState().login("old-token", AUTH_USER);
}

describe("ParamForm submit-time session renewal", () => {
  let onSubmitMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // mockReset clears both call history AND the once-queue, preventing stale
    // mockResolvedValueOnce values from leaking across tests.
    getMeMock.mockReset();
    apiFetchMock.mockReset();
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    // Default for all getMe calls: plenty of time → no mount-time refresh
    getMeMock.mockResolvedValue(meResponse(PLENTY_OF_TIME));
    apiFetchMock.mockResolvedValue(freshTokenResponse());
    onSubmitMock = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Click the generate button (shows the confirmation screen), then click
   * the confirm button (fires onSubmit + kicks off renewal).
   */
  async function clickGenerateThenConfirm(): Promise<void> {
    const generateButton = await screen.findByRole("button", {
      name: "form.btn_generate",
    });
    fireEvent.click(generateButton);
    const confirmButton = await screen.findByRole("button", {
      name: "form.btn_confirm_send",
    });
    fireEvent.click(confirmButton);
  }

  it("calls /auth/refresh on submit when the session is within the renewal threshold", async () => {
    signIn();
    // Mount call → plenty of time (no mount refresh)
    getMeMock.mockResolvedValueOnce(meResponse(PLENTY_OF_TIME));
    // Submit call → near expiry (should trigger refresh)
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));

    render(
      <ParamForm subject="math" onSubmit={onSubmitMock} disabled={false} />,
    );

    await clickGenerateThenConfirm();

    // onSubmit fires immediately (not blocked by async renewal)
    expect(onSubmitMock).toHaveBeenCalledTimes(1);

    // Refresh is requested asynchronously after confirm
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/auth/refresh", {
        method: "POST",
      });
    });
    expect(useAuthStore.getState().token).toBe("fresh-token");
    expect(localStorage.getItem("auth_token")).toBe("fresh-token");
  });

  it("does not call /auth/refresh on submit when the session has plenty of time remaining", async () => {
    signIn();
    // Default: all getMe calls return PLENTY_OF_TIME

    render(
      <ParamForm subject="math" onSubmit={onSubmitMock} disabled={false} />,
    );

    // Wait for mount-time check to complete
    await waitFor(() => {
      expect(getMeMock).toHaveBeenCalledTimes(1);
    });
    expect(apiFetchMock).not.toHaveBeenCalled();

    await clickGenerateThenConfirm();

    // Wait for submit-time renewal check to complete
    await waitFor(() => {
      expect(getMeMock).toHaveBeenCalledTimes(2);
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(onSubmitMock).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBe("old-token");
  });

  it("proceeds with generation even when the submit-time /auth/refresh request fails", async () => {
    signIn();
    getMeMock.mockResolvedValueOnce(meResponse(PLENTY_OF_TIME)); // mount: no refresh
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));    // submit: tries refresh

    // Refresh endpoint rejects on submit
    apiFetchMock.mockRejectedValueOnce(
      Object.assign(new Error("refresh failed"), { status: 500 }),
    );

    render(
      <ParamForm subject="math" onSubmit={onSubmitMock} disabled={false} />,
    );

    await clickGenerateThenConfirm();

    // Generation fires regardless of the refresh outcome
    expect(onSubmitMock).toHaveBeenCalledTimes(1);

    // Wait for the (failing) refresh attempt to settle
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledTimes(1);
    });

    // Token unchanged — refresh failed, error swallowed
    expect(useAuthStore.getState().token).toBe("old-token");
    // No error surfaced in the UI
    expect(screen.queryByText("refresh failed")).not.toBeInTheDocument();
  });

  it("calls /auth/refresh exactly once from the submit path when the mount check had plenty of time", async () => {
    signIn();
    // 1st call (mount): plenty of time — no refresh on mount
    getMeMock.mockResolvedValueOnce(meResponse(PLENTY_OF_TIME));
    // 2nd call (submit): near expiry — refresh on submit
    getMeMock.mockResolvedValueOnce(meResponse(NEAR_EXPIRY));

    render(
      <ParamForm subject="math" onSubmit={onSubmitMock} disabled={false} />,
    );

    // Wait for the mount-time check to complete and confirm no refresh happened
    await waitFor(() => {
      expect(getMeMock).toHaveBeenCalledTimes(1);
    });
    expect(apiFetchMock).not.toHaveBeenCalled();

    await clickGenerateThenConfirm();

    // Exactly one refresh — from the submit path only
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/auth/refresh", {
        method: "POST",
      });
    });
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(onSubmitMock).toHaveBeenCalledTimes(1);
  });
});
