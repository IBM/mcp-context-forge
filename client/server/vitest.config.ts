import { defineConfig } from "vitest/config";

// Standalone config so this package isn't swept up by client/vitest.config.ts
// (React/jsdom setup for the SPA) when vitest searches up the directory tree.
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    globals: false,
  },
});
