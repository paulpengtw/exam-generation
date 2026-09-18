import { describe, expect, it } from "vitest";
import type { HistoryDetail } from "../../api/client";
import {
  canonicalQuestionIdentity,
} from "../workspace/adapters/modificationWorkspace";
import type { ModificationWorkspaceSnapshot } from "../workspace/adapters/types";
import { validateModificationBase } from "./modificationValidation";

const question = {
  id: "question-1",
  題目: ["The saved question"],
  verification: { passed: true },
};

function snapshot(overrides: Partial<ModificationWorkspaceSnapshot> = {}): ModificationWorkspaceSnapshot {
  return {
    kind: "modification",
    version: 1,
    route: "/history/record-1",
    subject: "math",
    recordId: "record-1",
    questionId: "question-1",
    contentIdentity: canonicalQuestionIdentity(question),
    contentRevision: null,
    eligibility: { status: "completed", verified: true, eligible: true },
    annotations: [],
    replacement: null,
    ...overrides,
  };
}

function detail(overrides: Partial<HistoryDetail> = {}): HistoryDetail {
  return {
    id: "record-1",
    subject: "math",
    question_id: "question-1",
    created_at: "2026-09-17T00:00:00Z",
    status: "completed",
    error: null,
    generation_log_id: null,
    params_json: {},
    question_json: question,
    verification_trail: null,
    figure_policy_trail: null,
    reference_example_record: null,
    ...overrides,
  };
}

describe("validateModificationBase", () => {
  it("accepts the exact authorized History version and route", () => {
    expect(validateModificationBase(snapshot(), detail(), "/history/record-1")).toEqual({ valid: true });
  });

  it.each([
    ["route_changed", { route: "/history/other" }, detail()],
    ["record_changed", {}, detail({ id: "record-2" })],
    ["question_changed", {}, detail({ question_id: "question-2" })],
    ["subject_changed", {}, detail({ subject: "social_studies" })],
    ["content_changed", {}, detail({ question_json: { ...question, 題目: ["changed"] } })],
    ["ineligible", { eligibility: { status: "completed", verified: false, eligible: false } }, detail()],
    ["ineligible", {}, detail({ status: "failed" })],
    ["ineligible", {}, detail({ question_json: { ...question, verification: { passed: false } } })],
  ] as const)("blocks %s", (reason, snapshotOverrides, detailValue) => {
    expect(validateModificationBase(snapshot(snapshotOverrides), detailValue, "/history/record-1")).toEqual({
      valid: false,
      reason,
    });
  });

  it("blocks a known content revision change even when the JSON is otherwise equal", () => {
    expect(validateModificationBase(
      snapshot({ contentRevision: 4 }),
      detail({ question_json: { ...question, content_revision: 5 } }),
      "/history/record-1",
    )).toEqual({ valid: false, reason: "content_changed" });
  });
});
