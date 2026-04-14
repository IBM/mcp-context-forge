import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],

  // In dev the router uses /app/* paths directly; in production FastAPI
  // serves static assets from /static/app/ via StaticFiles.
  base: command === "build" ? "/static/app/" : "/",

  server: {
    proxy: {
      // Forward API/auth calls to the FastAPI backend
      "/auth": "http://localhost:4444",
      "/api": "http://localhost:4444",
    },
  },

  build: {
    // Output goes into mcpgateway/static/app/ — FastAPI serves /static/* from mcpgateway/static/
    outDir: "../mcpgateway/static/app",
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
  },
}));
