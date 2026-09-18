import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

const MODIFICATION_RECOVERY_KEYS = [
  "recovery.banner.modification_title",
  "recovery.modification_checking",
  "recovery.modification_restored",
  "recovery.modification_restore_failed",
  "recovery.modification_retry",
  "recovery.modification_blocked.route_changed",
  "recovery.modification_blocked.record_changed",
  "recovery.modification_blocked.question_changed",
  "recovery.modification_blocked.subject_changed",
  "recovery.modification_blocked.content_changed",
  "recovery.modification_blocked.ineligible",
  "recovery.modification_blocked.unauthorized",
  "recovery.modification_blocked.restore_failed",
] as const;

describe("coverage mode messages", () => {
  it("drops the 均衡 backend-assignment message from both locales", () => {
    expect(MESSAGES["en-US"]).not.toHaveProperty(
      "form.confirm_lc_balanced_backend_assignment",
    );
    expect(MESSAGES["zh-TW"]).not.toHaveProperty(
      "form.confirm_lc_balanced_backend_assignment",
    );
  });

  it("localizes every manual-review recovery message in both locales", () => {
    for (const key of MODIFICATION_RECOVERY_KEYS) {
      expect(MESSAGES["en-US"][key]).toEqual(expect.any(String));
      expect(MESSAGES["en-US"][key].trim()).not.toBe("");
      expect(MESSAGES["zh-TW"][key]).toEqual(expect.any(String));
      expect(MESSAGES["zh-TW"][key].trim()).not.toBe("");
    }
  });
});
