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
          generation_log_id: "log-abc",
          params_json: {},
          question_json: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const detail = await getHistoryDetail("abc");
    expect(detail.subject).toBe("social_studies");
    expect(detail.generation_log_id).toBe("log-abc");
  });

  it("keeps legacy history details readable when no generation log is linked", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "legacy",
          subject: "math",
          question_id: "math-1",
          created_at: "2026-07-15T00:00:00Z",
          generation_log_id: null,
          params_json: {},
          question_json: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const detail = await getHistoryDetail("legacy");

    expect(detail.generation_log_id).toBeNull();
  });

  it("downloadHistoryJson returns a Blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"a":1}', {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const blob = await downloadHistoryJson("abc");
    // Cross-realm jsdom pitfall: Response.blob() in node 20 returns a Blob from
    // the fetch/jsdom realm, which is a different object than the node global `Blob`.
    // `instanceof Blob` therefore fails on node 20 even when the value is a genuine
    // Blob. Use structural checks instead — they are realm-independent and strictly
    // stronger than instanceof (they also verify content, which instanceof never did).
    expect(typeof blob.text).toBe("function");
    expect(typeof blob.size).toBe("number");
    expect(blob.type).toBe("application/json");
    expect(await blob.text()).toBe('{"a":1}');
  });

  it("forwards an AbortSignal to history list requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ total: 0, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const controller = new AbortController();

    await listHistory({ signal: controller.signal });

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: controller.signal }));
  });

  it("forwards an AbortSignal to history download requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const controller = new AbortController();

    await downloadHistoryJson("abc", controller.signal);

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: controller.signal }));
  });
});
