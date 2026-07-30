import { describe, expect, it } from "vitest";

import type { FormParams } from "../components/ParamForm";
import { toGenerateParams } from "./toGenerateParams";

describe("toGenerateParams", () => {
  it("omits text_word_limit for math even when form state carries a stale value", () => {
    const params = toGenerateParams("math", {
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
});
