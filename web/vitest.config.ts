import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  define: {
    // Ensure React picks up the development build (which exports act)
    "process.env.NODE_ENV": JSON.stringify("development"),
    // Vite build-time defines — tests use stable placeholder values.
    // Individual test files that need specific values use vi.stubGlobal().
    __BUILD_ID__: JSON.stringify("test-build-id"),
    __BUILD_ENVIRONMENT__: JSON.stringify("test"),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
