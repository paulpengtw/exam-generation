import { describe, expect, it } from "vitest";
import type { FormParams } from "../../../components/ParamForm";
import type { ConfirmationWorkspaceSnapshot } from "./types";
import { exportConfirmationWorkspace, importConfirmationWorkspace } from "./confirmationWorkspace";

const pendingParams: FormParams & { subject: string } = {
  subject: "social_studies", grade: 8, context: ["公共"], set_type: "題組題",
  q_type: ["選擇題"], count: 2, skip_verify: false, image_generation_mode: "html",
  seed: 42, drawn: ["context", "per_question_params[0].subject_filter"],
  core_competency: ["社-J-A2"],
};

const live: Omit<ConfirmationWorkspaceSnapshot, "kind" | "version"> = {
  pendingParams,
  pendingPerQuestionParams: [{ subject_filter: ["地理"], learning_content: ["地Ab-IV-1"] }],
  clearedPaths: ["per_question_params[0].learning_content"],
  redraws: { "per_question_params[0].subject_filter": 2 },
  hasPendingConfirmationEdits: true,
  coreQuestionResolution: "generated",
  historyDraftChoice: "history",
};

describe("confirmation workspace adapter", () => {
  it("round-trips the completed payload and resolver provenance", () => {
    const snapshot = exportConfirmationWorkspace(live);
    expect(snapshot).toEqual({ ...live, kind: "confirmation", version: 1 });
    expect(importConfirmationWorkspace(JSON.parse(JSON.stringify(snapshot)))).toEqual(live);
  });

  it.each(["idle", "loading", "generated", "failed"] as const)("accepts core question resolution %s", (coreQuestionResolution) => {
    const state = { ...live, pendingPerQuestionParams: null, clearedPaths: [], redraws: {},
      hasPendingConfirmationEdits: false, coreQuestionResolution, historyDraftChoice: null };
    expect(importConfirmationWorkspace(exportConfirmationWorkspace(state))).toEqual(state);
  });

  it.each(["draft", "history", "defaults", null] as const)("accepts history/draft choice %s", (historyDraftChoice) => {
    const state = { ...live, historyDraftChoice };
    expect(importConfirmationWorkspace(exportConfirmationWorkspace(state))).toEqual(state);
  });

  it.each([null, 42, "confirmation", [], {}])("rejects a malformed envelope %#", (raw) => {
    expect(importConfirmationWorkspace(raw)).toBeNull();
  });

  it.each([
    { kind: "results" }, { version: 2 }, { version: "1" },
    { pendingParams: null }, { pendingParams: [] }, { pendingParams: {} },
    { pendingParams: { subject: 42 } },
    { pendingPerQuestionParams: {} }, { pendingPerQuestionParams: [null] }, { pendingPerQuestionParams: [[]] },
    { clearedPaths: [42] }, { clearedPaths: "context" },
    { redraws: [] }, { redraws: null }, { redraws: { context: "2" } },
    { redraws: { context: Number.NaN } }, { redraws: { context: Number.POSITIVE_INFINITY } },
    { hasPendingConfirmationEdits: "true" },
    { coreQuestionResolution: "ready" }, { historyDraftChoice: "restore" },
  ])("rejects invalid confirmation fields %#", (patch) => {
    expect(importConfirmationWorkspace({ ...live, kind: "confirmation", version: 1, ...patch })).toBeNull();
  });
});
