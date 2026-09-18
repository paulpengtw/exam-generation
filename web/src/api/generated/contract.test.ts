/**
 * SSE contract drift test: frontend handled event names must match the
 * server's generated vocabulary.
 *
 * If this test fails:
 * - A server event was added without a frontend handler: add a case in
 *   web/src/hooks/useGenerate.ts's onmessage switch.
 * - A frontend handler references an event the server cannot send: remove it
 *   or add the event to server/generate/marshalling.py:SSEEventName.
 */

import { describe, expect, it } from "vitest";

import { SSE_EMITTED_EVENT_NAMES } from "./contract";

// Event names handled in web/src/hooks/useGenerate.ts's fetchEventSource onmessage switch.
// Keep this list in sync with the cases in that switch statement.
const FRONTEND_HANDLED_EVENTS: ReadonlySet<string> = new Set([
  "started",
  "progress", // Declared-only on server; frontend still handles it defensively
  "llm_request",
  "llm_thinking",
  "llm_content",
  "llm_response",
  "stage",
  "plan",
  "pipeline",
  "question_update",
  "trail",
  "result",
  "question_terminal",
  "error",
  "done",
]);

// Full set of declared SSE names (emitted union declared-only).
// "progress" is the only declared-only name; it is not in SSE_EMITTED_EVENT_NAMES.
const ALL_DECLARED_EVENTS: ReadonlySet<string> = new Set([
  ...SSE_EMITTED_EVENT_NAMES,
  "progress", // declared in SSEEventName for wire-contract completeness; never emitted
]);

describe("SSE contract: frontend vs server event-name consistency", () => {
  it("every server-emitted event is handled by the frontend", () => {
    const unhandled = SSE_EMITTED_EVENT_NAMES.filter(
      (name) => !FRONTEND_HANDLED_EVENTS.has(name),
    );
    expect(unhandled).toEqual([]);
  });

  it("every frontend-handled event is declared in the server contract", () => {
    const undeclared = [...FRONTEND_HANDLED_EVENTS].filter(
      (name) => !ALL_DECLARED_EVENTS.has(name),
    );
    expect(undeclared).toEqual([]);
  });

  it("SSE_EMITTED_EVENT_NAMES has 14 entries (PROGRESS is declared-only)", () => {
    expect(SSE_EMITTED_EVENT_NAMES).toHaveLength(14);
  });

  it("ALL_DECLARED_EVENTS has 15 entries (14 emitted + 1 declared-only)", () => {
    expect(ALL_DECLARED_EVENTS.size).toBe(15);
  });
});
