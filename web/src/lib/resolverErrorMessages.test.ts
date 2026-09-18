import { describe, expect, it } from "vitest";

import {
  formatResolverFieldError,
  formatResolverFieldErrors,
  parseResolverFieldPath,
  type ResolverFieldErrorLike,
} from "./resolverErrorMessages";

// Fixture mirrors the server's field-addressed 422 detail shape:
// {field, code, parent}. `parent` is a real 科目/內容領域/情境 value for
// incompatible_parent, and the literal string "科目" | "內容領域" for
// no_admitting_parent (ADR: ../.superpowers/sdd/.../task-7-brief.md).
const INCOMPATIBLE_LC_SUBJECT: ResolverFieldErrorLike = {
  field: "learning_content",
  code: "incompatible_parent",
  parent: "地理",
};

const INCOMPATIBLE_LC_CONTENT_DOMAIN: ResolverFieldErrorLike = {
  field: "learning_content",
  code: "incompatible_parent",
  parent: "Civic Participation",
};

const INCOMPATIBLE_LP: ResolverFieldErrorLike = {
  field: "learning_performance",
  code: "incompatible_parent",
  parent: "跨科",
};

const NO_ADMITTING_SUBJECT: ResolverFieldErrorLike = {
  field: "learning_content",
  code: "no_admitting_parent",
  parent: "科目",
};

const NO_ADMITTING_CONTENT_DOMAIN: ResolverFieldErrorLike = {
  field: "learning_content",
  code: "no_admitting_parent",
  parent: "內容領域",
};

const BATCH_NO_ADMITTING_QUESTION2_SUB1: ResolverFieldErrorLike = {
  field: "per_question_params[1].subquestion_configs[0].learning_content",
  code: "no_admitting_parent",
  parent: "科目",
};

const SUBQUESTION_ONLY: ResolverFieldErrorLike = {
  field: "subquestion_configs[0].learning_content",
  code: "incompatible_parent",
  parent: "地理",
};

const SUB_CONTEXT_INCOMPATIBLE: ResolverFieldErrorLike = {
  field: "sub_context",
  code: "incompatible_parent",
  parent: "海洋教育",
};

const UNRESOLVED: ResolverFieldErrorLike = {
  field: "grade",
  code: "unresolved",
};

describe("parseResolverFieldPath", () => {
  it("extracts no position for a bare field", () => {
    expect(parseResolverFieldPath("learning_content")).toEqual({
      questionNumber: undefined,
      subquestionNumber: undefined,
      baseField: "learning_content",
    });
  });

  it("extracts 1-based 小題 position for subquestion_configs[j]", () => {
    expect(parseResolverFieldPath("subquestion_configs[0].learning_content")).toEqual({
      questionNumber: undefined,
      subquestionNumber: 1,
      baseField: "learning_content",
    });
  });

  it("extracts 1-based question and 小題 positions for a batched, per-小題 path", () => {
    expect(
      parseResolverFieldPath("per_question_params[1].subquestion_configs[0].learning_content"),
    ).toEqual({
      questionNumber: 2,
      subquestionNumber: 1,
      baseField: "learning_content",
    });
  });

  it("extracts only the question position when there is no subquestion segment", () => {
    expect(parseResolverFieldPath("per_question_params[0].learning_performance")).toEqual({
      questionNumber: 1,
      subquestionNumber: undefined,
      baseField: "learning_performance",
    });
  });
});

describe("formatResolverFieldError", () => {
  it("returns null for codes it does not format (unresolved)", () => {
    expect(formatResolverFieldError(UNRESOLVED, "zh-TW")).toBeNull();
    expect(formatResolverFieldError(UNRESOLVED, "en-US")).toBeNull();
  });

  it("formats incompatible_parent naming 科目 in zh-TW", () => {
    expect(formatResolverFieldError(INCOMPATIBLE_LC_SUBJECT, "zh-TW")).toBe(
      "所選的學習內容不屬於科目「地理」。",
    );
  });

  it("formats incompatible_parent naming 科目 in en-US", () => {
    expect(formatResolverFieldError(INCOMPATIBLE_LC_SUBJECT, "en-US")).toBe(
      "The selected learning content does not belong to the subject \"地理\".",
    );
  });

  it("infers 內容領域 (not 科目) when the parent value is not one of the four 社會 科目 values", () => {
    expect(formatResolverFieldError(INCOMPATIBLE_LC_CONTENT_DOMAIN, "zh-TW")).toBe(
      "所選的學習內容不屬於內容領域「Civic Participation」。",
    );
  });

  it("formats a 學習表現 child with the 科目 parent kind (學習表現 has no 內容領域 parent)", () => {
    expect(formatResolverFieldError(INCOMPATIBLE_LP, "zh-TW")).toBe(
      "所選的學習表現不屬於科目「跨科」。",
    );
    expect(formatResolverFieldError(INCOMPATIBLE_LP, "en-US")).toBe(
      "The selected learning performance does not belong to the subject \"跨科\".",
    );
  });

  it("formats no_admitting_parent for 科目 in both languages", () => {
    expect(formatResolverFieldError(NO_ADMITTING_SUBJECT, "zh-TW")).toBe(
      "所選的學習內容沒有共同可用的科目，請移除部分代碼。",
    );
    expect(formatResolverFieldError(NO_ADMITTING_SUBJECT, "en-US")).toBe(
      "The selected learning content has no common subject available; remove some of the selected codes.",
    );
  });

  it("formats no_admitting_parent for 內容領域 in both languages", () => {
    expect(formatResolverFieldError(NO_ADMITTING_CONTENT_DOMAIN, "zh-TW")).toBe(
      "所選的學習內容沒有共同可用的內容領域，請移除部分代碼。",
    );
    expect(formatResolverFieldError(NO_ADMITTING_CONTENT_DOMAIN, "en-US")).toBe(
      "The selected learning content has no common content domain available; remove some of the selected codes.",
    );
  });

  it("names the 1-based question and 小題 position for a batched per-小題 field (question 2, 小題 1)", () => {
    expect(formatResolverFieldError(BATCH_NO_ADMITTING_QUESTION2_SUB1, "zh-TW")).toBe(
      "第2題第1小題所選的學習內容沒有共同可用的科目，請移除部分代碼。",
    );
    expect(formatResolverFieldError(BATCH_NO_ADMITTING_QUESTION2_SUB1, "en-US")).toBe(
      "In question 2, sub-question 1, the selected learning content has no common subject available; remove some of the selected codes.",
    );
  });

  it("names only the 小題 position when there is no per_question_params prefix", () => {
    expect(formatResolverFieldError(SUBQUESTION_ONLY, "zh-TW")).toBe(
      "第1小題所選的學習內容不屬於科目「地理」。",
    );
    expect(formatResolverFieldError(SUBQUESTION_ONLY, "en-US")).toBe(
      "In sub-question 1, the selected learning content does not belong to the subject \"地理\".",
    );
  });

  it("treats sub_context as a child of 情境 regardless of the parent value", () => {
    expect(formatResolverFieldError(SUB_CONTEXT_INCOMPATIBLE, "zh-TW")).toBe(
      "所選的情境子類別不屬於情境「海洋教育」。",
    );
    expect(formatResolverFieldError(SUB_CONTEXT_INCOMPATIBLE, "en-US")).toBe(
      "The selected sub-context does not belong to the context \"海洋教育\".",
    );
  });
});

describe("formatResolverFieldErrors", () => {
  it("returns null for an empty array", () => {
    expect(formatResolverFieldErrors([], "zh-TW")).toBeNull();
  });

  it("joins multiple readable sentences", () => {
    expect(
      formatResolverFieldErrors([INCOMPATIBLE_LC_SUBJECT, NO_ADMITTING_CONTENT_DOMAIN], "zh-TW"),
    ).toBe(
      "所選的學習內容不屬於科目「地理」。 所選的學習內容沒有共同可用的內容領域，請移除部分代碼。",
    );
  });

  it("bails out to null (caller falls back) when any entry is not a readable code", () => {
    expect(formatResolverFieldErrors([INCOMPATIBLE_LC_SUBJECT, UNRESOLVED], "zh-TW")).toBeNull();
    expect(formatResolverFieldErrors([UNRESOLVED], "en-US")).toBeNull();
  });
});
