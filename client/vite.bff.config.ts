import { mergeConfig, defineConfig } from "vite";

import baseConfig from "./vite.config";

// Alternate build target for the BFF-served SPA: outputs to
// client/server/public/ with base '/', instead of vite.config.ts's default
// (mcpgateway/static/app/ with base '/static/app/', for FastAPI's existing
// static mount). Everything else — plugins, chunking, etc. — is inherited
// from the base config. See client/server/src/plugins/static.ts.
export default mergeConfig(
  baseConfig,
  defineConfig({
    base: "/",
    build: {
      outDir: "server/public",
      emptyOutDir: true,
    },
  })
);
