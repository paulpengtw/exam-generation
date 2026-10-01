/**
 * issue #946 — i18n key parity test.
 *
 * Asserts every one of the 10 LLM-failure taxonomy codes has both
 * `error.class.<code>` and `error.class_hint.<code>` keys in BOTH
 * `en-US` and `zh-TW` locales.
 *
 * Also verifies that `parseErrorPayload` falls back to a generic message
 * when failure_class is absent or unknown.
 */

import { describe, it, expect } from "vitest";
import { MESSAGES } from "./messages";
import { parseErrorPayload } from "../hooks/useGenerate";

const TAXONOMY_CODES = [
  "auth_config",
  "quota_billing_exhausted",
  "rate_limited",
  "overloaded",
  "timeout",
  "connection",
  "context_length",
  "content_filtered",
  "malformed_response",
  "unknown",
] as const;

const LOCALES = ["en-US", "zh-TW"] as const;

describe("i18n parity — error.class.* and error.class_hint.* (issue #946)", () => {
  for (const locale of LOCALES) {
    describe(`locale ${locale}`, () => {
      for (const code of TAXONOMY_CODES) {
        it(`has error.class.${code}`, () => {
          const msg = MESSAGES[locale][`error.class.${code}`];
          expect(msg, `Missing error.class.${code} in ${locale}`).toBeTruthy();
          expect(typeof msg, `error.class.${code} must be a string in ${locale}`).toBe("string");
        });

        it(`has error.class_hint.${code}`, () => {
          const hint = MESSAGES[locale][`error.class_hint.${code}`];
          expect(hint, `Missing error.class_hint.${code} in ${locale}`).toBeTruthy();
          expect(typeof hint, `error.class_hint.${code} must be a string in ${locale}`).toBe("string");
        });
      }
    });
  }

  it("teacher-actionable codes do NOT mention administrator in en-US", () => {
    const teacherCodes = ["rate_limited", "overloaded", "timeout", "connection", "context_length", "malformed_response"];
    for (const code of teacherCodes) {
      const hint = MESSAGES["en-US"][`error.class_hint.${code}`];
      expect(hint).not.toContain("administrator");
    }
  });

  it("admin-only codes mention administrator in en-US", () => {
    const adminCodes = ["auth_config", "quota_billing_exhausted"];
    for (const code of adminCodes) {
      const hint = MESSAGES["en-US"][`error.class_hint.${code}`];
      expect(hint).toContain("administrator");
    }
  });

  it("admin-only codes mention 管理員 in zh-TW", () => {
    const adminCodes = ["auth_config", "quota_billing_exhausted"];
    for (const code of adminCodes) {
      const hint = MESSAGES["zh-TW"][`error.class_hint.${code}`];
      expect(hint).toContain("管理員");
    }
  });
});

describe("parseErrorPayload — fallback to generic message when unknown/absent (issue #946)", () => {
  it("unknown code → failureClass=null (falls back to raw message)", () => {
    const result = parseErrorPayload(JSON.stringify({ message: "err", failure_class: "not_valid" }));
    expect(result.failureClass).toBeNull();
    expect(result.message).toBe("err");
  });

  it("absent failure_class → failureClass=null", () => {
    const result = parseErrorPayload(JSON.stringify({ message: "something failed" }));
    expect(result.failureClass).toBeNull();
    expect(result.message).toBe("something failed");
  });

  it("null failure_class → failureClass=null", () => {
    const result = parseErrorPayload(JSON.stringify({ message: "err", failure_class: null }));
    expect(result.failureClass).toBeNull();
  });
});
