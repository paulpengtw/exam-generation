import { beforeEach, describe, expect, it } from "vitest";

import {
  consumeReturnDestination,
  isAllowedDestination,
  saveReturnDestination,
} from "./returnDestination";

describe("returnDestination", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  // ── isAllowedDestination allowlist ──────────────────────────────────────────

  describe("isAllowedDestination", () => {
    it("accepts /generate/math", () => {
      expect(isAllowedDestination("/generate/math")).toBe(true);
    });

    it("accepts /generate/social_studies", () => {
      expect(isAllowedDestination("/generate/social_studies")).toBe(true);
    });

    it("accepts /generate/natural_sciences", () => {
      expect(isAllowedDestination("/generate/natural_sciences")).toBe(true);
    });

    it("rejects /history", () => {
      expect(isAllowedDestination("/history")).toBe(false);
    });

    it("rejects /generate (subject picker — not a form route)", () => {
      expect(isAllowedDestination("/generate")).toBe(false);
    });

    it("rejects /generate/other (unknown subject)", () => {
      expect(isAllowedDestination("/generate/other")).toBe(false);
    });

    it("rejects an external URL", () => {
      expect(isAllowedDestination("https://evil.example")).toBe(false);
    });

    it("rejects empty string", () => {
      expect(isAllowedDestination("")).toBe(false);
    });
  });

  // ── save / consume round-trip ───────────────────────────────────────────────

  describe("save + consume round-trip", () => {
    it("saves and returns /generate/math", () => {
      saveReturnDestination("/generate/math");
      expect(consumeReturnDestination()).toBe("/generate/math");
    });

    it("saves and returns /generate/social_studies", () => {
      saveReturnDestination("/generate/social_studies");
      expect(consumeReturnDestination()).toBe("/generate/social_studies");
    });

    it("saves and returns /generate/natural_sciences", () => {
      saveReturnDestination("/generate/natural_sciences");
      expect(consumeReturnDestination()).toBe("/generate/natural_sciences");
    });

    it("consume clears the stored value so a second consume returns null", () => {
      saveReturnDestination("/generate/social_studies");
      consumeReturnDestination();
      expect(consumeReturnDestination()).toBeNull();
    });

    it("does NOT save a disallowed path (/history)", () => {
      saveReturnDestination("/history");
      expect(consumeReturnDestination()).toBeNull();
    });

    it("does NOT save an external URL", () => {
      saveReturnDestination("https://evil.example");
      expect(consumeReturnDestination()).toBeNull();
    });

    it("returns null when nothing is stored", () => {
      expect(consumeReturnDestination()).toBeNull();
    });

    it("returns null (and clears) when a manually written invalid path is stored", () => {
      localStorage.setItem("exam_return_to", "https://evil.example");
      expect(consumeReturnDestination()).toBeNull();
      // Cleared even though the value was invalid
      expect(localStorage.getItem("exam_return_to")).toBeNull();
    });

    it("clears the stored value even when it fails the allowlist check", () => {
      localStorage.setItem("exam_return_to", "/history");
      consumeReturnDestination();
      expect(localStorage.getItem("exam_return_to")).toBeNull();
    });
  });
});
