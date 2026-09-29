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
let rejectSubmission: boolean;
let rejectionDetail: unknown;
let runFinished: boolean;
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
  rejectSubmission = false;
  runFinished = true;
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
      // Detached runs (issue #908): acceptance is a plain 202 JSON body.
      response.writeHead(202, { "Content-Type": "application/json" });
      response.end(JSON.stringify({
        run_id: "transport-run",
        protocol_version: 3,
        total: 1,
        questions: [{ index: 0, question_id: "transport-result" }],
      }));
      return;
    }
    if (request.url === "/api/runs/transport-run") {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({
        run_id: "transport-run",
        status: runFinished ? "completed" : "running",
        subject: "math",
        total: 1,
        started_at: "2026-09-14T00:00:00+00:00",
        completed_at: runFinished ? "2026-09-14T00:01:00+00:00" : null,
        error: null,
        questions: [runFinished
          ? {
            index: 0,
            question_id: "transport-result",
            processing: "ended",
            current_step: null,
            termination_reason: "normal",
            terminal: {
              termination_reason: "normal", has_final: true, final_revision: 1,
              delivery_status: "complete", expected: [], delivered: [], missing: [],
              review: { status: "passed", content_revision: 1 },
            },
            error: null,
            result: {
              record_id: "record-1",
              question: { id: "transport-result", 題目: ["完整題目"] },
              verification_trail: [], figure_policy_trail: [], reference_example_record: null,
            },
          }
          : {
            index: 0, question_id: "transport-result", processing: "running",
            current_step: "text", termination_reason: null, terminal: null, error: null, result: null,
          }],
      }));
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

it.each(batches)("submits a large complete $subject batch once and reads its result over HTTP", async (batch) => {
  const payload = { ...batch, text_instruction: "保留每個題組和小題的完整出題指示。".repeat(100) };
  const { result } = renderHook(() => useGenerate());
  act(() => { void result.current.generate(payload); });
  await waitFor(() => expect(result.current.status).toBe("idle"), { timeout: 8000 });
  expect(result.current.errorMessage).toBeNull();
  expect(result.current.results).toEqual([{ id: "transport-result", 題目: ["完整題目"] }]);
  expect(received.filter((r) => r.method === "POST")).toEqual([{
    url: "/api/generate", method: "POST", body: { ...payload, stream_version: 3 },
    authorization: "Bearer test-token",
  }]);
  // Everything after the submission is a read of the run, never a write.
  expect(received.slice(1).every((r) => r.method === "GET" && r.url === "/api/runs/transport-run")).toBe(true);
  expect(received.slice(1).every((r) => r.authorization === "Bearer test-token")).toBe(true);
}, 15_000);

it("retains the run ID from the acceptance at the real HTTP boundary and stops on reset", async () => {
  runFinished = false;
  const { result } = renderHook(() => useGenerate());

  act(() => { void result.current.generate(socialBatch); });

  await waitFor(() => expect(result.current.generationLogId).toBe("transport-run"));
  expect(result.current.status).toBe("generating");

  act(() => result.current.reset());
  expect(result.current.generationLogId).toBeNull();
  expect(result.current.status).toBe("idle");
  // Reset only stops watching locally: no further request, cancel or otherwise.
  await new Promise((resolve) => setTimeout(resolve, 3300));
  expect(received).toHaveLength(1);
}, 10_000);

it("reports a rejected POST with its field address and does not retry generation", async () => {
  rejectSubmission = true;
  const { result } = renderHook(() => useGenerate());
  act(() => { result.current.generate(naturalBatch); });
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
  act(() => { result.current.generate(payload); });
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
      tags: { source: "generateSubmit", navigator_online: "true" },
      contexts: { submit: { elapsed_ms: expect.any(Number) } },
    },
  );
  const [error, context] = captureException.mock.calls[0];
  expect(`${error.message} ${JSON.stringify(error)} ${JSON.stringify(context)}`).not.toContain("PRIVATE_");
  // A rejected submission is final: it is not retried.
  await new Promise((resolve) => setTimeout(resolve, 1100));
  expect(received).toEqual([{
    url: "/api/generate", method: "POST", body: { ...payload, stream_version: 3 },
    authorization: "Bearer test-token",
  }]);
});
