import { defineConfig, mergeConfig } from "vite";

import baseConfig from "./vite.config";

const entry = process.env.STACK_FIT_ENTRY ?? "./src/research/StackFitBuildWithMotion.tsx";

export default defineConfig(
  mergeConfig(baseConfig, {
    build: {
      outDir: "dist-stack-fit",
      emptyOutDir: true,
      rollupOptions: {
        input: entry,
      },
    },
  }),
);
