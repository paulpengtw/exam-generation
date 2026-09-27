/**
 * T5 (issue #754): Ensure the test-harness never enters the production build.
 *
 * Guards:
 * 1. tsconfig.app.json must include only "src" (not "test-harness").
 * 2. No production source file (under src/) imports from "test-harness/".
 *
 * The post-build check `! grep -r "__harness" dist/` in the verification
 * command provides the run-time guarantee; this test provides the compile-time
 * guarantee so CI catches regressions before a build is needed.
 */
import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const WEB_ROOT = path.resolve(import.meta.dirname, "../..");
const SRC_ROOT = path.resolve(WEB_ROOT, "src");

function walkFiles(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(full));
    } else if (entry.isFile()) {
      files.push(full);
    }
  }
  return files;
}

describe("test-harness production guard (T5)", () => {
  it("tsconfig.app.json does not reference test-harness", () => {
    const tsconfigPath = path.join(WEB_ROOT, "tsconfig.app.json");
    const raw = fs.readFileSync(tsconfigPath, "utf-8");
    // tsconfig uses JSONC syntax (comments), so check raw text rather than parsing
    expect(
      raw,
      "tsconfig.app.json must not reference test-harness"
    ).not.toMatch(/test-harness/);
    // Also confirm it includes "src" (sanity check)
    expect(raw, "tsconfig.app.json should include 'src'").toMatch(/"src"/);
  });

  it("no src/ file imports from ../test-harness or web/test-harness", () => {
    const srcFiles = walkFiles(SRC_ROOT).filter(
      (f) => f.endsWith(".ts") || f.endsWith(".tsx")
    );
    const violations: string[] = [];
    for (const file of srcFiles) {
      // Skip this test file itself
      if (file.endsWith("testHarnessProductionGuard.test.ts")) continue;
      const content = fs.readFileSync(file, "utf-8");
      if (/['"](\.\.\/)*test-harness\//.test(content) || /__harness/.test(content)) {
        violations.push(path.relative(WEB_ROOT, file));
      }
    }
    expect(violations, "Production source files must not reference test-harness").toEqual([]);
  });
});
