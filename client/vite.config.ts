import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],

  // Use "/" for dev server, "/static/app/" for production build
  // Assets are served from /static/app/ by FastAPI's StaticFiles mount in production
  base: mode === "production" ? "/static/app/" : "/",

  // Proxy API requests to FastAPI backend during development
  server: {
    proxy: {
      // Proxy all API endpoints to the FastAPI backend
      "/auth": {
        target: "http://localhost:4444",
        changeOrigin: true,
      },
      "/api": {
        target: "http://localhost:4444",
        changeOrigin: true,
      },
      "/mcp": {
        target: "http://localhost:4444",
        changeOrigin: true,
      },
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
