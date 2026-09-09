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
    coreQuestionCallback: true,
    imageGenerationMode: "html",
    difficulty: "",
    reportingScale: "",
    subjectFilter: "數與量",
    passage: "500 字",
    textWordLimit: null,
    textInstruction: "",
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
    modelVerify: "",
    modelCorrect: "",
    effortPlan: "medium",
    effortExecute: "medium",
    effortVerify: "",
    effortCorrect: "",
    allowDuplicateFigureKinds: false,
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

  it("round-trips textInstruction and normalises legacy drafts without it", () => {
    type FieldsWithTextInstruction = FormFields & { textInstruction: string };
    const fields = {
      ...makeFields(),
      textInstruction: "請聚焦地方自治中的證據比較",
    } as FieldsWithTextInstruction;

    saveDraft("teacher-1", fields);
    expect(
      (loadDraft("teacher-1")?.fields as FieldsWithTextInstruction).textInstruction,
    ).toBe("請聚焦地方自治中的證據比較");

    saveDraft("teacher-1", makeFields());
    expect(
      (loadDraft("teacher-1")?.fields as FieldsWithTextInstruction).textInstruction,
    ).toBe("");
  });

  it("loads a legacy draft without reportingScale and normalizes it to an empty string", () => {
    const fields = Object.fromEntries(
      Object.entries(makeFields()).filter(([key]) => key !== "reportingScale"),
    );
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({ savedAt: NOW.toISOString(), fields }),
    );

    expect(loadDraft("teacher-1")?.fields.reportingScale).toBe("");
  });

  it("loads a legacy draft without coreQuestionCallback and defaults it on", () => {
    const fields = Object.fromEntries(
      Object.entries(makeFields()).filter(([key]) => key !== "coreQuestionCallback"),
    );
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({ savedAt: NOW.toISOString(), fields }),
    );

    expect(loadDraft("teacher-1")?.fields.coreQuestionCallback).toBe(true);
  });

  it("rejects a draft with a non-string reportingScale", () => {
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({
        savedAt: NOW.toISOString(),
        fields: { ...makeFields(), reportingScale: 42 },
      }),
    );

    expect(loadDraft("teacher-1")).toBeNull();
  });

  it("round-trips a string reportingScale", () => {
    saveDraft("teacher-1", makeFields({ reportingScale: "2" }));

    expect(loadDraft("teacher-1")?.fields.reportingScale).toBe("2");
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

  it("loads a draft saved by an older build (without modelVerify/modelCorrect) and normalises missing fields to empty string", () => {
    // Simulate a draft persisted before issue #376 added modelVerify / modelCorrect.
    const oldFields = makeFields({ topic: "舊版草稿" });
    const { modelVerify: _v, modelCorrect: _c, ...fieldsWithoutNewKeys } = oldFields;
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({
        savedAt: NOW.toISOString(),
        fields: fieldsWithoutNewKeys,
      }),
    );

    const draft = loadDraft("teacher-1");
    expect(draft).not.toBeNull();
    expect(draft?.fields.topic).toBe("舊版草稿");
    // Missing fields must be normalised to "" rather than left as undefined.
    expect(draft?.fields.modelVerify).toBe("");
    expect(draft?.fields.modelCorrect).toBe("");
  });

  it("loads a draft saved by an older build (without effortVerify/effortCorrect) and normalises missing fields to empty string", () => {
    // Simulate a draft persisted before issue #377 added effortVerify / effortCorrect.
    const oldFields = makeFields({ topic: "效能草稿" });
    const { effortVerify: _ev, effortCorrect: _ec, ...fieldsWithoutNewKeys } = oldFields;
    localStorage.setItem(
      "exam_form_draft_teacher-1",
      JSON.stringify({
        savedAt: NOW.toISOString(),
        fields: fieldsWithoutNewKeys,
      }),
    );

    const draft = loadDraft("teacher-1");
    expect(draft).not.toBeNull();
    expect(draft?.fields.topic).toBe("效能草稿");
    // Missing fields must be normalised to "" (inherit) rather than left as undefined.
    expect(draft?.fields.effortVerify).toBe("");
    expect(draft?.fields.effortCorrect).toBe("");
  });
});
