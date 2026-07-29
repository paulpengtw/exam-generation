import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

describe("coverage mode labels", () => {
  it("describes 出題模式 as a prompt-level hint in both locales", () => {
    expect(MESSAGES["zh-TW"]["form.coverage_mode.balanced"]).toBe(
      "均衡（提示模型平均分配）",
    );
    expect(MESSAGES["en-US"]["form.coverage_mode.balanced"]).toBe(
      "Balanced (prompt-level hint)",
    );
  });
});
