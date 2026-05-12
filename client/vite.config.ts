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
  },
});
