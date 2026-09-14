import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

describe("prefill dropped codes messages", () => {
  it("provides the dropped codes notice with an items placeholder in both locales", () => {
    for (const locale of ["en-US", "zh-TW"] as const) {
      expect(MESSAGES[locale]).toHaveProperty("history.prefill_dropped_codes");
      expect(MESSAGES[locale]["history.prefill_dropped_codes"]).toContain("{items}");
    }
  });
});
