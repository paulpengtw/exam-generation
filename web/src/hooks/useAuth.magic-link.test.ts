/**
 * Regression guard: the magic-link request body must NEVER include a redirect
 * or return_to parameter (issue #243).
 *
 * The return destination lives only in this browser's localStorage — it must
 * not be embedded in the magic-link email URL, because clicking the link in a
 * different browser (e.g. an in-app mail browser) would be a different storage
 * context and the remembered destination would not be there.
 */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

vi.mock("../store/authStore", () => ({
  useAuthStore: (
    selector: (state: {
      token: null;
      user: null;
      login: () => void;
      logout: () => void;
      isAuthenticated: () => boolean;
    }) => unknown,
  ) =>
    selector({
      token: null,
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
      isAuthenticated: () => false,
    }),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import { useAuth } from "./useAuth";

describe("useAuth.sendMagicLink — no redirect field in request body", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("sends exactly { email, lang } with no redirect-related field", async () => {
    const { result } = renderHook(() => useAuth());
    await act(async () => {
      await result.current.sendMagicLink("user@example.com");
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/auth/magic-link");

    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    // Required fields
    expect(body).toHaveProperty("email", "user@example.com");
    expect(body).toHaveProperty("lang", "en-US");
    // Must NOT contain any redirect-related key
    expect(body).not.toHaveProperty("redirect");
    expect(body).not.toHaveProperty("return_to");
    expect(body).not.toHaveProperty("returnTo");
    expect(body).not.toHaveProperty("next");
    expect(body).not.toHaveProperty("redirect_uri");
  });
});
