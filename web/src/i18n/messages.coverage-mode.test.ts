import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

describe("coverage mode messages", () => {
  it("drops the 均衡 backend-assignment message from both locales", () => {
    expect(MESSAGES["en-US"]).not.toHaveProperty(
      "form.confirm_lc_balanced_backend_assignment",
    );
    expect(MESSAGES["zh-TW"]).not.toHaveProperty(
      "form.confirm_lc_balanced_backend_assignment",
    );
  });
});
