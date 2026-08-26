import { afterEach, describe, expect, it, vi } from "vitest";

import { getAvailableModels, resolveGenerate } from "./client";

const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

vi.mock("../store/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: null, logout: () => {} }),
  },
}));

afterEach(() => {
  fetchMock.mockReset();
});

describe("getAvailableModels", () => {
  it("returns allowed + defaults from the JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
          defaults: {
            plan: "claude-opus-4-6",
            execute: "claude-sonnet-4-6",
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await getAvailableModels();
    expect(result).toEqual({
      allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
      defaults: {
        plan: "claude-opus-4-6",
        execute: "claude-sonnet-4-6",
      },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/models",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("throws ApiError when the response is non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('{"detail":"nope"}', {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(getAvailableModels()).rejects.toThrow("nope");
  });
});

describe("resolveGenerate", () => {
  it("posts the partial payload and redraw counters to the resolver", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          payload: { subject: "math", seed: 17, learning_content: ["RESOLVED-LC"] },
          drawn: ["learning_content"],
          cleared: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const payload = { subject: "math", seed: 17, learning_content: [] };
    const result = await resolveGenerate(payload, { learning_content: 2 });

    expect(result).toEqual({
      payload: { subject: "math", seed: 17, learning_content: ["RESOLVED-LC"] },
      drawn: ["learning_content"],
      cleared: [],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generate/resolve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ ...payload, redraws: { learning_content: 2 } }),
      }),
    );
  });
});
