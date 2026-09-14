import { beforeEach, describe, expect, it } from "vitest";
import type { FormFields } from "../../../components/ParamForm";
import { loadDraft, parseFormFields, saveDraft } from "../../formDraft";
import { exportFormWorkspace, importFormWorkspace } from "./formWorkspace";

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

beforeEach(() => localStorage.clear());

describe("form workspace adapter", () => {
  it("round-trips FormFields including per-subquestion configuration", () => {
    const fields = makeFields({
      topic: "臺灣河川", count: 3,
      subquestionConfigs: [{ question_type: "選擇題", instruction: "比較資料", learning_content: ["N-7-1"], learning_performance: ["n-IV-1"] }],
    });
    const snapshot = exportFormWorkspace(fields);
    expect(snapshot).toEqual({ kind: "form", version: 1, fields });
    expect(importFormWorkspace(JSON.parse(JSON.stringify(snapshot)))).toEqual(fields);
    expect(parseFormFields(fields)).toEqual(fields);
  });

  it.each([
    ["modelVerify", "modelCorrect"],
    ["effortVerify", "effortCorrect"],
    ["textInstruction"],
    ["reportingScale"],
    ["coreQuestionCallback"],
    ["allowDuplicateFigureKinds"],
    ["modelVerify", "modelCorrect", "effortVerify", "effortCorrect", "textInstruction", "reportingScale", "coreQuestionCallback", "allowDuplicateFigureKinds"],
  ])("normalises legacy fields exactly like loadDraft: %j", (...missing) => {
    const legacy: Record<string, unknown> = { ...makeFields() };
    for (const key of missing) delete legacy[key];
    saveDraft("u1", legacy as unknown as FormFields);
    const viaDraft = loadDraft("u1")?.fields ?? null;
    expect(viaDraft).toEqual(makeFields());
    expect(parseFormFields(legacy)).toEqual(makeFields());
    expect(importFormWorkspace({ kind: "form", version: 1, fields: legacy })).toEqual(viaDraft);
    for (const key of missing) expect(legacy).not.toHaveProperty(key);
  });

  it("preserves optional ICCS fields without adding defaults", () => {
    const fields = makeFields({ contentDomain: "公民社會與制度", targetSurface: "數位" });
    saveDraft("u1", fields);
    expect(importFormWorkspace(exportFormWorkspace(fields))).toEqual(loadDraft("u1")?.fields);
    expect(parseFormFields(makeFields())).not.toHaveProperty("contentDomain");
    expect(parseFormFields(makeFields())).not.toHaveProperty("targetSurface");
  });

  it.each([
    null, 42, [], { kind: "form" },
    { kind: "results", version: 1, fields: makeFields() },
    { kind: "form", version: 2, fields: makeFields() },
    { kind: "form", version: 1, fields: { grade: "x" } },
    { kind: "form", version: 1, fields: makeFields({ subquestionConfigs: [{ learning_content: [42] } as unknown as FormFields["subquestionConfigs"][number]] }) },
  ])("rejects malformed snapshot %#", (raw) => {
    expect(importFormWorkspace(raw)).toBeNull();
  });

  it.each([
    null, 42, [], {},
    { ...makeFields(), count: Number.NaN },
    { ...makeFields(), context: "個人" },
    { ...makeFields(), coreQuestionCallback: "true" },
    { ...makeFields(), reportingScale: 2 },
    { ...makeFields(), subquestionConfigs: [{ option_word_limit: Number.POSITIVE_INFINITY }] },
  ])("rejects malformed fields without throwing %#", (raw) => {
    expect(parseFormFields(raw)).toBeNull();
  });
});
