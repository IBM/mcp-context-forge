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
    rollupOptions: {
      external: (id) => /\.(test|spec)\.(ts|tsx|js|jsx)$/.test(id),
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (
            id.includes("/react/") ||
            id.includes("/react-dom/") ||
            id.includes("/scheduler/") ||
            id.includes("/react-is/") ||
            id.includes("/react-remove-scroll") ||
            id.includes("/react-style-singleton") ||
            id.includes("/use-callback-ref") ||
            id.includes("/use-sidecar") ||
            id.includes("react-intl") ||
            id.includes("@formatjs") ||
            id.includes("/sonner/")
          ) return "vendor-react";
          if (id.includes("@radix-ui") || id.includes("radix-ui")) return "vendor-radix";
          if (id.includes("lucide-react")) return "vendor-lucide";
          return "vendor";
        },
      },
    },
  },
});
