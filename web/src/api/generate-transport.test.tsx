import { createServer, type Server } from "node:http";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const captureException = vi.hoisted(() => vi.fn());
vi.mock("@sentry/react", () => ({ captureException }));

import socialBatch from "../../../tests/fixtures/transport-social-batch.json";
import naturalBatch from "../../../tests/fixtures/transport-natural-batch.json";
import { useAuthStore } from "../store/authStore";
import { useGenerate } from "../hooks/useGenerate";
import { previewGenerate } from "./client";

const originalFetch = globalThis.fetch;
let server: Server;
let received: { url?: string; method?: string; body: unknown; authorization?: string }[];
let holdStream: boolean;
let streamClosed: boolean;
let rejectSubmission: boolean;
let rejectionDetail: unknown;
const batches = [socialBatch, naturalBatch, {
  subject: "math", seed: 41, grade: 8, context: ["個人"], set_type: "單一題",
  q_type: ["選擇題"], style: ["text_only"], math_thinking: ["形成"],
  learning_content: ["A-7-7"], learning_performance: ["s-IV-12"],
  core_competency: ["數-J-A2"], content_type: "純文字",
}];

beforeEach(async () => {
  captureException.mockClear();
  vi.stubEnv("VITE_SENTRY_DSN", "https://public@example.com/1");
  received = [];
  holdStream = false;
  streamClosed = false;
  rejectSubmission = false;
  rejectionDetail = [{
    field: "per_question_params[0].subquestion_configs[0].question_type", code: "unresolved",
  }];
  server = createServer({ maxHeaderSize: 1_000_000 }, async (request, response) => {
    // Reproduce the deployed proxy's request-line limit at the HTTP boundary.
    if ((request.url?.length ?? 0) > 8192) {
      response.writeHead(414).end();
      return;
    }
    let raw = "";
    for await (const chunk of request) raw += chunk;
    received.push({
      url: request.url, method: request.method, body: raw ? JSON.parse(raw) : null,
      authorization: request.headers.authorization,
    });
    if (rejectSubmission) {
      response.writeHead(422, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ detail: rejectionDetail }));
      return;
    }
    if (request.url === "/api/generate") {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      if (holdStream) {
        response.write('event: started\ndata: {}\n\n');
        response.on("close", () => { streamClosed = true; });
        return;
      }
      response.end('event: started\ndata: {}\n\nevent: result\ndata: {"id":"transport-result","題目":["完整題目"]}\n\nevent: done\ndata: {}\n\n');
      return;
    }
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      prompts: [{ index: 0, system_prompt: "系統提示", user_prompt: "完整預覽" }],
    }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing test HTTP port");
  const base = `http://127.0.0.1:${address.port}`;
  // Resolve the browser's relative URLs; the real HTTP client and SSE parser run unchanged.
  vi.stubGlobal("fetch", (input: string, init?: RequestInit) =>
    originalFetch(new URL(input, base), init));
  useAuthStore.getState().login("test-token", {
    id: "test-user", email: "transport@example.com", created_at: "2026-09-14",
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

it.each(batches)("previews a complete large $subject batch over HTTP without shortening its parameters", async (batch) => {
  const payload = {
    ...batch,
    text_instruction: "請根據地方自治的證據比較不同立場，保留完整的中文出題指示。".repeat(100),
  };
  const result = await previewGenerate(payload);
  expect(result.prompts[0].user_prompt).toBe("完整預覽");
  expect(received).toEqual([{
    url: "/api/generate/preview", method: "POST", body: payload,
    authorization: "Bearer test-token",
  }]);
});

it.each(batches)("submits a large complete $subject batch once and receives its SSE result", async (batch) => {
  const payload = { ...batch, text_instruction: "保留每個題組和小題的完整出題指示。".repeat(100) };
  const { result } = renderHook(() => useGenerate());
  act(() => result.current.generate(payload));
  await waitFor(() => expect(result.current.status).toBe("idle"));
  expect(result.current.errorMessage).toBeNull();
  expect(result.current.results).toEqual([{ id: "transport-result", 題目: ["完整題目"] }]);
  expect(received).toEqual([{
    url: "/api/generate", method: "POST", body: payload,
    authorization: "Bearer test-token",
  }]);
});

it("cancels an active POST stream without starting another generation", async () => {
  holdStream = true;
  const { result } = renderHook(() => useGenerate());
  act(() => result.current.generate(socialBatch));
  await waitFor(() => expect(received).toHaveLength(1));
  expect(result.current.status).toBe("generating");
  act(() => result.current.reset());
  await waitFor(() => expect(streamClosed).toBe(true));
  expect(result.current.status).toBe("idle");
  expect(result.current.errorMessage).toBeNull();
  expect(received).toHaveLength(1);
});

it("reports a rejected POST with its field address and does not retry generation", async () => {
  rejectSubmission = true;
  const { result } = renderHook(() => useGenerate());
  act(() => result.current.generate(naturalBatch));
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.errorMessage).toContain("per_question_params[0].subquestion_configs[0].question_type");
  expect(result.current.results).toEqual([]);
  expect(received).toHaveLength(1);
});

it("shows the nested field and validation message when a malformed POST is rejected", async () => {
  rejectSubmission = true;
  rejectionDetail = [{
    type: "value_error",
    loc: ["body", "per_question_params", 0, "math_thinking"],
    msg: "Value error, math_thinking must contain 1 to 3 values",
    input: { private: "PRIVATE_INPUT_787" },
    ctx: { error: "PRIVATE_CONTEXT_787" },
  }];
  const payload = {
    subject: "math",
    count: 1,
    per_question_params: JSON.stringify([{ math_thinking: [] }]),
  };
  const { result } = renderHook(() => useGenerate());
  act(() => result.current.generate(payload));
  await waitFor(() => expect(result.current.status).toBe("error"));
  render(<div role="alert">{result.current.errorMessage}</div>);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Invalid request: per_question_params[0].math_thinking: Value error, math_thinking must contain 1 to 3 values",
  );
  expect(screen.getByRole("alert")).not.toHaveTextContent("PRIVATE_");
  expect(result.current.results).toEqual([]);
  expect(result.current.llmCalls).toEqual([]);
  expect(captureException).toHaveBeenCalledExactlyOnceWith(
    new Error("Invalid request: per_question_params[0].math_thinking: Value error, math_thinking must contain 1 to 3 values"),
    {
      tags: {
        source: "fetchEventSource", last_event_type: "none", navigator_online: "true",
      },
      contexts: { stream: { elapsed_ms: expect.any(Number), message_count: 0 } },
    },
  );
  const [error, context] = captureException.mock.calls[0];
  expect(`${error.message} ${JSON.stringify(error)} ${JSON.stringify(context)}`).not.toContain("PRIVATE_");
  // fetch-event-source retries after 1s unless the HTTP rejection is fatal.
  await new Promise((resolve) => setTimeout(resolve, 1100));
  expect(received).toEqual([{
    url: "/api/generate", method: "POST", body: payload,
    authorization: "Bearer test-token",
  }]);
});
