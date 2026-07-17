import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../store/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: "TOK", logout: vi.fn() }),
  },
}));

import { downloadHistoryJson, getHistoryDetail, listHistory } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("history api client", () => {
  it("listHistory builds a query string with limit/offset/subject", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ total: 1, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await listHistory({ limit: 5, offset: 10, subject: "math" });
    const url = (fetchMock.mock.calls[0][0] as string) || "";
    expect(url).toContain("/api/history?");
    expect(url).toContain("limit=5");
    expect(url).toContain("offset=10");
    expect(url).toContain("subject=math");
  });

  it("getHistoryDetail returns parsed JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "abc",
          subject: "social_studies",
          question_id: "ss_1",
          created_at: "2026-07-15T00:00:00Z",
          params_json: {},
          question_json: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const detail = await getHistoryDetail("abc");
    expect(detail.subject).toBe("social_studies");
  });

  it("downloadHistoryJson returns a Blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"a":1}', {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const blob = await downloadHistoryJson("abc");
    expect(blob).toBeInstanceOf(Blob);
  });
});
