/**
 * A scriptable stand-in for the detached-run endpoints (issue #908):
 * `POST /api/generate` (202 acceptance) and `GET /api/runs/{id}` (snapshot).
 * Installs itself as the global `fetch` and records every request, so tests
 * can assert both what was sent and that nothing else (e.g. a cancel) was.
 */
import { vi } from "vitest";

import type { AcceptedRun, RunSnapshot } from "../lib/runSnapshot";
import { acceptedRun } from "./runFixtures";

export interface RecordedRequest {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface FakeRunServer {
  requests: RecordedRequest[];
  /** GET /api/runs/{id} requests only. */
  polls(): RecordedRequest[];
  /** POST /api/generate requests only. */
  submits(): RecordedRequest[];
  /** Snapshot returned for a run id from now on. */
  setSnapshot(runId: string, snapshot: RunSnapshot): void;
  /** Make a run id answer 404 (unknown, or owned by someone else). */
  hideRun(runId: string): void;
  /** Next submit answers with this status/body instead of a 202. */
  failSubmit(status: number, body: unknown): void;
  /** Override the 202 body of the next submit(s). */
  setAcceptance(accepted: AcceptedRun): void;
  /** Make every poll reject like a dropped connection until cleared. */
  dropConnection(dropped: boolean): void;
  restore(): void;
}

function headersOf(init: RequestInit | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  new Headers(init?.headers).forEach((value, key) => {
    out[key.toLowerCase()] = value;
  });
  return out;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function installFakeRunServer(): FakeRunServer {
  const originalFetch = globalThis.fetch;
  const requests: RecordedRequest[] = [];
  const snapshots = new Map<string, RunSnapshot>();
  const hidden = new Set<string>();
  let submitFailure: { status: number; body: unknown } | null = null;
  let acceptance: AcceptedRun | null = null;
  let dropped = false;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = null;
    if (typeof init?.body === "string") {
      try { body = JSON.parse(init.body); } catch { body = init.body; }
    }
    requests.push({ method, url, headers: headersOf(init), body });

    if (method === "POST" && url === "/api/generate") {
      if (submitFailure) {
        const failure = submitFailure;
        submitFailure = null;
        return json(failure.status, failure.body);
      }
      const count = typeof (body as { count?: unknown } | null)?.count === "number"
        ? (body as { count: number }).count
        : 1;
      return json(202, acceptance ?? acceptedRun(count));
    }
    const match = /^\/api\/runs\/([^/]+)$/.exec(url);
    if (method === "GET" && match) {
      if (dropped) throw new TypeError("Failed to fetch");
      const id = decodeURIComponent(match[1]);
      const snapshot = snapshots.get(id);
      if (hidden.has(id) || !snapshot) return json(404, { detail: "run not found" });
      return json(200, snapshot);
    }
    return json(404, { detail: `unexpected ${method} ${url}` });
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    requests,
    polls: () => requests.filter((r) => r.method === "GET" && r.url.startsWith("/api/runs/")),
    submits: () => requests.filter((r) => r.method === "POST" && r.url === "/api/generate"),
    setSnapshot: (runId, snapshot) => { snapshots.set(runId, snapshot); hidden.delete(runId); },
    hideRun: (runId) => { hidden.add(runId); },
    failSubmit: (status, body) => { submitFailure = { status, body }; },
    setAcceptance: (accepted) => { acceptance = accepted; },
    dropConnection: (value) => { dropped = value; },
    restore: () => { vi.stubGlobal("fetch", originalFetch); },
  };
}
