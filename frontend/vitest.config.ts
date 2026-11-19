import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "node",
    environmentMatchGlobs: [["**/*.test.tsx", "jsdom"]],
    setupFiles: ["./vitest.setup.ts"],
    // Heavy jsdom tests take <1 s alone but can pass 5 s when the full suite runs in parallel.
    testTimeout: 20_000,
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules", ".next"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
