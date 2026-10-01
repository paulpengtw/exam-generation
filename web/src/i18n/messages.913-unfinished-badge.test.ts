/**
 * Completeness check for the 6 new i18n strings added by issue #913.
 */
import { describe, expect, it } from "vitest";
import { MESSAGES } from "./messages";

const KEYS_913 = [
  "history.unfinished_title",
  "history.run_running",
  "history.run_cancelling",
  "history.run_queued",
  "history.unfinished_error",
  "history.badge_label",
] as const;

describe("issue #913 i18n strings", () => {
  for (const locale of ["en-US", "zh-TW"] as const) {
    describe(`locale ${locale}`, () => {
      for (const key of KEYS_913) {
        it(`has non-empty string for "${key}"`, () => {
          expect(MESSAGES[locale]).toHaveProperty(key);
          const value = MESSAGES[locale][key];
          expect(typeof value).toBe("string");
          expect((value as string).length).toBeGreaterThan(0);
        });
      }

      it('history.run_queued contains "{k}" placeholder', () => {
        expect(MESSAGES[locale]["history.run_queued"]).toContain("{k}");
      });
    });
  }
});
