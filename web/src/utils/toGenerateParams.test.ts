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
});
