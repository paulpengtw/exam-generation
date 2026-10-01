/**
 * i18n parity guard for keys added on branch feat/748-754-live-progress-export.
 * Every key in BRANCH_KEYS_754 must exist in both en-US and zh-TW and must not
 * be the empty string.
 *
 * Source: git diff cee2162..HEAD -- web/src/i18n/messages.ts
 */
import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

const BRANCH_KEYS_754 = [
  "odt.preview_conversion_failed",
  // T1 (#752): ODT marker strings moved from hard-coded to i18n
  "odt.draft_notice",
  "odt.known_missing_image_stem",
  "odt.known_missing_subquestion",
  "odt.known_missing_subq_image",
  "odt.known_missing_image_flat",
  "history.download_odt_error",
  "history.btn_download_odt",
  "stream.information_incomplete",
  "stream.batch_conflict",
  "stream.legacy_mixed",
  "card.content_conflict",
  "card.conflict_reason_seq_data",
  "card.conflict_reason_same_revision_different_content",
  "card.conflict_reason_identity_mismatch",
  "card.conflict_reason_terminal_contradiction",
  "card.conflict_reason_terminal_invalid",
  "card.conflict_reason_review_contradiction",
  "card.position_unknown",
  "stream.legacy_no_per_question_progress",
  "statusbar.legacy_request_total",
  "card.download_json_draft",
  "card.download_odt_draft",
  "generate.run_read_unavailable",
] as const;

describe("754 branch i18n key parity", () => {
  for (const key of BRANCH_KEYS_754) {
    it(`"${key}" exists and is non-empty in both en-US and zh-TW`, () => {
      const enVal = MESSAGES["en-US"][key];
      const zhVal = MESSAGES["zh-TW"][key];

      expect(enVal, `en-US["${key}"] missing`).toBeDefined();
      expect(typeof enVal, `en-US["${key}"] must be string`).toBe("string");
      expect((enVal as string).trim(), `en-US["${key}"] must not be empty`).not.toBe("");

      expect(zhVal, `zh-TW["${key}"] missing`).toBeDefined();
      expect(typeof zhVal, `zh-TW["${key}"] must be string`).toBe("string");
      expect((zhVal as string).trim(), `zh-TW["${key}"] must not be empty`).not.toBe("");

      // en and zh should differ (they're different languages)
      expect(enVal, `en-US and zh-TW translations for "${key}" must differ`).not.toBe(zhVal);
    });
  }

  it("all 24 branch keys are present (count check)", () => {
    expect(BRANCH_KEYS_754).toHaveLength(24);
    const enKeys = new Set(Object.keys(MESSAGES["en-US"]));
    const zhKeys = new Set(Object.keys(MESSAGES["zh-TW"]));
    for (const key of BRANCH_KEYS_754) {
      expect(enKeys.has(key), `en-US missing "${key}"`).toBe(true);
      expect(zhKeys.has(key), `zh-TW missing "${key}"`).toBe(true);
    }
  });
});
