import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],

  css: {
    postcss: {
      plugins: [],
    },
  },

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  // Assets are served from /static/app/ by FastAPI's StaticFiles mount
  base: "/static/app/",

  build: {
    // Output goes into mcpgateway/static/app/ — FastAPI serves /static/* from mcpgateway/static/
    outDir: "../mcpgateway/static/app",
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
    // 1 MB is comfortable for a single-bundle admin UI loaded once per session.
    // Raising the warning limit keeps build output free of false alarms; the
    // gzipped payload is ~300 kB.
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      external: (id) => /\.(test|spec)\.(ts|tsx|js|jsx)$/.test(id),
      // manualChunks was previously used to split vendor code by library, but
      // any split that put recharts in a different chunk from React broke
      // Rollup's CJS interop, producing "Cannot read properties of undefined
      // (reading 'forwardRef')" at module init. Until we can validate a split
      // that holds together with React 19 + react-intl + recharts, ship as a
      // single bundle.
    },
  },
});
