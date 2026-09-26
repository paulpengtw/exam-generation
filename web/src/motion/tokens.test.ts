import { beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { writeMotionTokens } from "./tokens";

const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

const expectedTokens = {
  "--motion-duration-quick": "150ms",
  "--motion-duration-standard": "320ms",
  "--motion-duration-loop-shimmer": "2250ms",
  "--motion-duration-loop-spinner": "900ms",
  "--motion-ease-signature": "cubic-bezier(0.22,1,0.36,1)",
  "--motion-ease-exit": "cubic-bezier(0.64,0,0.78,0)",
  "--motion-ease-loop": "cubic-bezier(0.25,0.1,0.25,1)",
  "--motion-travel": "8px",
  "--motion-stagger": "40ms",
  "--motion-stagger-cap": "400ms",
  "--motion-handoff-delay": "100ms",
} as const;

describe("writeMotionTokens", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("style");
  });

  it("writes every motion token to the root with its exact value", () => {
    writeMotionTokens();

    for (const [property, value] of Object.entries(expectedTokens)) {
      expect(document.documentElement.style.getPropertyValue(property)).toBe(value);
    }
  });

  it("keeps the reduced-motion contract in the stylesheet", () => {
    expect(indexCss).toContain("@media (prefers-reduced-motion: reduce)");
    expect(indexCss).toContain("transition-duration: 1ms !important");
    expect(indexCss).toContain("transition-property: opacity !important");
    expect(indexCss).toContain("motion-opacity-pulse");
    expect(indexCss).toContain(".streaming-caret");
    expect(indexCss).toContain("transform: none !important");
  });
});
