/**
 * A scriptable stand-in for the detached-run endpoints (issue #908):
 * `POST /api/generate` (202 acceptance), `GET /api/runs` (list), and
 * `GET /api/runs/{id}` (snapshot).
 * Installs itself as the global `fetch` and records every request, so tests
 * can assert both what was sent and that nothing else (e.g. a cancel) was.
 */
import { vi } from "vitest";

import type { RunListItem } from "../api/client";
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
  /** GET /api/runs (list) requests only. */
  listPolls(): RecordedRequest[];
  /** POST /api/generate requests only. */
  submits(): RecordedRequest[];
  /** POST /api/runs/{id}/cancel requests only. */
  cancels(): RecordedRequest[];
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
  /**
   * Make POST /api/generate throw TypeError (network error) until cleared.
   * Unlike failSubmit (which returns an HTTP error), this simulates a
   * connection-level failure so useGenerate keeps the submission key for retry.
   */
  dropSubmitConnection(dropped: boolean): void;
  /** Next cancel request answers with this status/body instead of a 200. */
  failCancel(status: number, body: unknown): void;
  /** Set the run list returned by GET /api/runs. */
  setRunList(items: RunListItem[]): void;
  /** Make GET /api/runs return an error status. */
  failRunList(status: number, body: unknown): void;
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
  let cancelFailure: { status: number; body: unknown } | null = null;
  let runListFailure: { status: number; body: unknown } | null = null;
  let acceptance: AcceptedRun | null = null;
  let dropped = false;
  let submitDropped = false;
  let runList: RunListItem[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = null;
    if (typeof init?.body === "string") {
      try { body = JSON.parse(init.body); } catch { body = init.body; }
    }
    requests.push({ method, url, headers: headersOf(init), body });

    if (method === "POST" && url === "/api/generate") {
      if (submitDropped) throw new TypeError("Failed to fetch");
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
    // GET /api/runs (list) — must come before the /{id} regex
    if (method === "GET" && url === "/api/runs") {
      if (runListFailure) {
        const failure = runListFailure;
        runListFailure = null;
        return json(failure.status, failure.body);
      }
      return json(200, runList);
    }
    const match = /^\/api\/runs\/([^/]+)$/.exec(url);
    if (method === "GET" && match) {
      if (dropped) throw new TypeError("Failed to fetch");
      const id = decodeURIComponent(match[1]);
      const snapshot = snapshots.get(id);
      if (hidden.has(id) || !snapshot) return json(404, { detail: "run not found" });
      return json(200, snapshot);
    }
    const cancelMatch = /^\/api\/runs\/([^/]+)\/cancel$/.exec(url);
    if (method === "POST" && cancelMatch) {
      const id = decodeURIComponent(cancelMatch[1]);
      if (cancelFailure) {
        const failure = cancelFailure;
        cancelFailure = null;
        return json(failure.status, failure.body);
      }
      if (hidden.has(id) || !snapshots.has(id)) return json(404, { detail: "run not found" });
      return json(200, { cancelled: true });
    }
    return json(404, { detail: `unexpected ${method} ${url}` });
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    requests,
    polls: () => requests.filter((r) => r.method === "GET" && /^\/api\/runs\/[^/]+$/.test(r.url)),
    listPolls: () => requests.filter((r) => r.method === "GET" && r.url === "/api/runs"),
    submits: () => requests.filter((r) => r.method === "POST" && r.url === "/api/generate"),
    cancels: () => requests.filter((r) => r.method === "POST" && r.url.includes("/cancel")),
    setSnapshot: (runId, snapshot) => { snapshots.set(runId, snapshot); hidden.delete(runId); },
    hideRun: (runId) => { hidden.add(runId); },
    failSubmit: (status, body) => { submitFailure = { status, body }; },
    failCancel: (status, body) => { cancelFailure = { status, body }; },
    setAcceptance: (accepted) => { acceptance = accepted; },
    dropConnection: (value) => { dropped = value; },
    dropSubmitConnection: (value) => { submitDropped = value; },
    setRunList: (items) => { runList = items; },
    failRunList: (status, body) => { runListFailure = { status, body }; },
    restore: () => { vi.stubGlobal("fetch", originalFetch); },
  };
}
