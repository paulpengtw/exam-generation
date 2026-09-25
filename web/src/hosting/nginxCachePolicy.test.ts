/**
 * Static assertions on the nginx configuration files.
 *
 * Nginx and Docker are not available in this container — the headers are
 * verified by string/regex assertions on the config files directly.
 *
 * Issue #770: cache-control directives for release metadata, assets, and
 * the SPA entry-point / fallback.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Resolve from the web/ directory (this file lives under src/hosting/)
const WEB_DIR = join(__dirname, "../..");

function readConfig(filename: string): string {
  return readFileSync(join(WEB_DIR, filename), "utf-8");
}

const CONFIGS = [
  { label: "nginx.conf", content: readConfig("nginx.conf") },
  { label: "nginx.conf.template", content: readConfig("nginx.conf.template") },
];

for (const { label, content } of CONFIGS) {
  describe(`${label}`, () => {
    // ── /release/policy.json ──────────────────────────────────────────────
    it("serves /release/policy.json with Cache-Control no-store", () => {
      // Must have an exact-match location block
      expect(content).toMatch(/location\s*=\s*\/release\/policy\.json/);
      // Within that block, no-store header
      expect(content).toContain("Cache-Control 'no-store'");
    });

    it("/release/policy.json is served by the live controller", () => {
      expect(content).toMatch(
        /location\s*=\s*\/release\/policy\.json[^}]*proxy_pass/s,
      );
    });

    // ── /build-meta.json ──────────────────────────────────────────────────
    it("serves /build-meta.json with Cache-Control no-store", () => {
      expect(content).toMatch(/location\s*=\s*\/build-meta\.json/);
      // Both metadata locations share no-store
      const noStoreMatches = (content.match(/Cache-Control 'no-store'/g) ?? []).length;
      expect(noStoreMatches).toBeGreaterThanOrEqual(2);
    });

    it("/build-meta.json is served by the live controller", () => {
      expect(content).toMatch(
        /location\s*=\s*\/build-meta\.json[^}]*proxy_pass/s,
      );
    });

    // ── /assets/ ──────────────────────────────────────────────────────────
    it("serves /assets/ with immutable Cache-Control", () => {
      expect(content).toMatch(/location\s+\/assets\//);
      expect(content).toContain("Cache-Control 'public, max-age=31536000, immutable'");
    });

    it("/assets/ uses try_files $uri =404 (no index.html fallback)", () => {
      expect(content).toMatch(
        /location\s+\/assets\/[^}]*try_files\s+\$uri\s+=404/s,
      );
    });

    it("/assets/ does NOT fall back to index.html", () => {
      // Extract the assets location block
      const assetsBlock = content.match(
        /location\s+\/assets\/\s*\{[^}]+\}/s,
      );
      expect(assetsBlock).not.toBeNull();
      expect(assetsBlock![0]).not.toContain("index.html");
    });

    // ── /index.html ───────────────────────────────────────────────────────
    it("serves /index.html with Cache-Control no-cache", () => {
      expect(content).toMatch(/location\s*=\s*\/index\.html/);
      expect(content).toContain("Cache-Control 'no-cache'");
    });

    // ── SPA fallback ──────────────────────────────────────────────────────
    it("SPA fallback location / has no-cache header", () => {
      // The catch-all location block must have no-cache
      expect(content).toMatch(/location\s+\/\s*\{[^}]*Cache-Control 'no-cache'/s);
    });

    it("SPA fallback location / still serves index.html for non-asset paths", () => {
      expect(content).toMatch(/location\s+\/\s*\{[^}]*\/index\.html/s);
    });

    // ── Proxy locations intact ────────────────────────────────────────────
    it("keeps /auth/ proxy location", () => {
      expect(content).toMatch(/location\s+\/auth\//);
      expect(content).toMatch(/proxy_pass/);
    });

    it("keeps /api/ proxy location", () => {
      expect(content).toMatch(/location\s+\/api\//);
    });

    it("keeps /health proxy location", () => {
      expect(content).toMatch(/location\s+\/health/);
    });
  });
}
