import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FormFields } from "../components/ParamForm";
import { loadDraft, saveDraft } from "./formDraft";

const NOW = new Date("2026-07-30T12:00:00.000Z");

function makeFields(overrides: Partial<FormFields> = {}): FormFields {
  return {
    grade: 7,
    style: "課本",
    contentType: "純文字",
    customContentType: "",
    context: ["個人"],
    setType: "單一題",
    qType: ["選擇題"],
    count: 1,
    coverageMode: "balanced",
    skipVerify: false,
    disableReferenceFewshot: false,
    imageGenerationMode: "html",
    difficulty: "",
    subjectFilter: "數與量",
    passage: "500 字",
    textWordLimit: null,
    options: ["50 字", "50 字", "50 字", "50 字"],
    topic: "",
    coreQuestion: null,
    subContext: "",
    scienceCompetency: [],
    learningPerformance: [],
    learningContent: [],
    subQuestionCount: "",
    subquestionConfigs: [],
    modelPlan: "",
    modelExecute: "",
    effortPlan: "medium",
    effortExecute: "medium",
    ...overrides,
  };
}

describe("formDraft", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("saves and loads a draft round-trip", () => {
    const fields = makeFields({ topic: "臺灣河川", count: 3 });

    saveDraft("teacher-1", fields);

    expect(loadDraft("teacher-1")).toEqual({
      savedAt: NOW.toISOString(),
      fields,
    });
  });

  it("removes and returns null for a draft older than seven days", () => {
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({
        savedAt: new Date(
          NOW.getTime() - 7 * 24 * 60 * 60 * 1000 - 1,
        ).toISOString(),
        fields: makeFields(),
      }),
    );

    expect(loadDraft("teacher-1")).toBeNull();
    expect(localStorage.getItem("exam_form_draft_teacher-1")).toBeNull();
  });

  it("isolates drafts by user id", () => {
    saveDraft("teacher-1", makeFields({ topic: "教師一" }));
    saveDraft("teacher-2", makeFields({ topic: "教師二" }));

    expect(loadDraft("teacher-1")?.fields.topic).toBe("教師一");
    expect(loadDraft("teacher-2")?.fields.topic).toBe("教師二");
  });

  it("removes corrupt JSON and returns null", () => {
    localStorage.setItem("exam_form_draft_teacher-1", "{not-json");

    expect(loadDraft("teacher-1")).toBeNull();
    expect(localStorage.getItem("exam_form_draft_teacher-1")).toBeNull();
  });

  it("removes structurally invalid draft fields and returns null", () => {
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({
        savedAt: NOW.toISOString(),
        fields: { ...makeFields(), context: "not-an-array" },
      }),
    );

    expect(loadDraft("teacher-1")).toBeNull();
    expect(localStorage.getItem("exam_form_draft_teacher-1")).toBeNull();
  });
});
