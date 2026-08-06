import { describe, expect, it } from "vitest";

import type { FormParams } from "../components/ParamForm";
import { toGenerateParams } from "./toGenerateParams";

describe("toGenerateParams", () => {
  it("forwards text_word_limit for math", () => {
    const params = toGenerateParams("math", {
      text_word_limit: 321,
    } as FormParams);

    expect(params.text_word_limit).toBe(321);
  });

  it("forwards sub_question_count for math", () => {
    const params = toGenerateParams("math", {
      sub_question_count: 4,
    } as FormParams);

    expect(params.sub_question_count).toBe(4);
  });

  it("omits the math limit when the form carries user-authored 文本", () => {
    const params = toGenerateParams("math", {
      passage: "使用者提供的文本",
      text_word_limit: 321,
    } as FormParams);

    expect(params.text_word_limit).toBeUndefined();
  });

  // ── Slice 4: reporting_scale mapping ────────────────────────────────────────
  describe("natural_sciences reporting_scale / difficulty routing", () => {
    it("sends reporting_scale for natural_sciences when set", () => {
      const params = toGenerateParams("natural_sciences", {
        reporting_scale: "4",
        difficulty: "easy",
      } as FormParams);
      expect(params.reporting_scale).toBe("4");
    });

    it("omits difficulty for natural_sciences even when form carries a value", () => {
      const params = toGenerateParams("natural_sciences", {
        difficulty: "easy",
        reporting_scale: "3",
      } as FormParams);
      expect(params.difficulty).toBeUndefined();
    });

    it("sends difficulty for math and omits reporting_scale", () => {
      const params = toGenerateParams("math", {
        difficulty: "hard",
        reporting_scale: "4",
      } as FormParams);
      expect(params.difficulty).toBe("hard");
      expect(params.reporting_scale).toBeUndefined();
    });

    it("sends difficulty for social_studies and omits reporting_scale", () => {
      const params = toGenerateParams("social_studies", {
        difficulty: "medium",
        reporting_scale: "2",
      } as FormParams);
      expect(params.difficulty).toBe("medium");
      expect(params.reporting_scale).toBeUndefined();
    });
  });

  // ── Issue #338: effort passthrough ──────────────────────────────────────────
  describe("effort passthrough", () => {
    it("passes effort_plan and effort_execute through to the returned params", () => {
      const params = toGenerateParams("math", {
        effort_plan: "high",
        effort_execute: "low",
      } as FormParams);

      expect(params.effort_plan).toBe("high");
      expect(params.effort_execute).toBe("low");
    });

    it("leaves effort_plan and effort_execute undefined when not provided", () => {
      const params = toGenerateParams("math", {} as FormParams);

      expect(params.effort_plan).toBeUndefined();
      expect(params.effort_execute).toBeUndefined();
    });
  });
});
