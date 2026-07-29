import { describe, expect, it } from "vitest";

import { MESSAGES } from "./messages";

const statusbarEntries = (locale: keyof typeof MESSAGES) =>
  Object.entries(MESSAGES[locale]).filter(([key]) =>
    key.startsWith("statusbar."),
  );

describe("status bar messages", () => {
  it("keeps non-empty localized messages in parity", () => {
    const enEntries = statusbarEntries("en-US");
    const zhEntries = statusbarEntries("zh-TW");
    const enKeys = new Set(enEntries.map(([key]) => key));
    const zhKeys = new Set(zhEntries.map(([key]) => key));

    expect(enKeys).toEqual(zhKeys);
    expect(enKeys.size).toBeGreaterThan(0);
    for (const [, value] of [...enEntries, ...zhEntries]) {
      expect(typeof value).toBe("string");
      expect(value.trim()).not.toBe("");
    }
    expect(MESSAGES["en-US"]["statusbar.not_started"]).not.toBe(
      MESSAGES["zh-TW"]["statusbar.not_started"],
    );
  });
});
