// vitest.config.ts
import { defineConfig } from "file:///E:/mcp-context-forge/client/node_modules/vitest/dist/config.js";
import react from "file:///E:/mcp-context-forge/client/node_modules/@vitejs/plugin-react/dist/index.js";
import path from "path";
var __vite_injected_original_dirname = "E:\\mcp-context-forge\\client";
var vitest_config_default = defineConfig({
  plugins: [react()],
  css: {
    postcss: {
      plugins: []
    }
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    testTimeout: 3e4,
    // Vitest runs Testing-Library specs under src/; Playwright specs live
    // under e2e/ and must not be picked up here (they use @playwright/test).
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", "dist", "e2e", "playwright-report", "test-results"],
    typecheck: {
      include: ["src/**/*.test.{ts,tsx}"]
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      exclude: [
        "node_modules/",
        "e2e/",
        "src/test/",
        "src/types/",
        "**/types.ts",
        "src/main.tsx",
        "**/*.d.ts",
        "**/*.config.*",
        "**/mockData",
        "**/*.test.{ts,tsx}"
      ],
      thresholds: {
        statements: 95,
        branches: 95,
        functions: 95,
        lines: 95
      }
    }
  },
  resolve: {
    alias: {
      "@": path.resolve(__vite_injected_original_dirname, "./src")
    }
  }
});
export {
  vitest_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZXN0LmNvbmZpZy50cyJdLAogICJzb3VyY2VzQ29udGVudCI6IFsiY29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2Rpcm5hbWUgPSBcIkU6XFxcXG1jcC1jb250ZXh0LWZvcmdlXFxcXGNsaWVudFwiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9maWxlbmFtZSA9IFwiRTpcXFxcbWNwLWNvbnRleHQtZm9yZ2VcXFxcY2xpZW50XFxcXHZpdGVzdC5jb25maWcudHNcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfaW1wb3J0X21ldGFfdXJsID0gXCJmaWxlOi8vL0U6L21jcC1jb250ZXh0LWZvcmdlL2NsaWVudC92aXRlc3QuY29uZmlnLnRzXCI7Ly8vIDxyZWZlcmVuY2UgdHlwZXM9XCJ2aXRlc3RcIiAvPlxuLy8vIDxyZWZlcmVuY2UgdHlwZXM9XCJAdGVzdGluZy1saWJyYXJ5L2plc3QtZG9tXCIgLz5cbmltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gXCJ2aXRlc3QvY29uZmlnXCI7XG5pbXBvcnQgcmVhY3QgZnJvbSBcIkB2aXRlanMvcGx1Z2luLXJlYWN0XCI7XG5pbXBvcnQgcGF0aCBmcm9tIFwicGF0aFwiO1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbcmVhY3QoKV0gYXMgYW55LFxuICBjc3M6IHtcbiAgICBwb3N0Y3NzOiB7XG4gICAgICBwbHVnaW5zOiBbXSxcbiAgICB9LFxuICB9LFxuICB0ZXN0OiB7XG4gICAgZ2xvYmFsczogdHJ1ZSxcbiAgICBlbnZpcm9ubWVudDogXCJqc2RvbVwiLFxuICAgIHNldHVwRmlsZXM6IFwiLi9zcmMvdGVzdC9zZXR1cC50c1wiLFxuICAgIGNzczogdHJ1ZSxcbiAgICB0ZXN0VGltZW91dDogMzAwMDAsXG4gICAgLy8gVml0ZXN0IHJ1bnMgVGVzdGluZy1MaWJyYXJ5IHNwZWNzIHVuZGVyIHNyYy87IFBsYXl3cmlnaHQgc3BlY3MgbGl2ZVxuICAgIC8vIHVuZGVyIGUyZS8gYW5kIG11c3Qgbm90IGJlIHBpY2tlZCB1cCBoZXJlICh0aGV5IHVzZSBAcGxheXdyaWdodC90ZXN0KS5cbiAgICBpbmNsdWRlOiBbXCJzcmMvKiovKi57dGVzdCxzcGVjfS57dHMsdHN4fVwiXSxcbiAgICBleGNsdWRlOiBbXCJub2RlX21vZHVsZXNcIiwgXCJkaXN0XCIsIFwiZTJlXCIsIFwicGxheXdyaWdodC1yZXBvcnRcIiwgXCJ0ZXN0LXJlc3VsdHNcIl0sXG4gICAgdHlwZWNoZWNrOiB7XG4gICAgICBpbmNsdWRlOiBbXCJzcmMvKiovKi50ZXN0Lnt0cyx0c3h9XCJdLFxuICAgIH0sXG4gICAgY292ZXJhZ2U6IHtcbiAgICAgIHByb3ZpZGVyOiBcInY4XCIsXG4gICAgICByZXBvcnRlcjogW1widGV4dFwiLCBcImpzb25cIiwgXCJodG1sXCJdLFxuICAgICAgZXhjbHVkZTogW1xuICAgICAgICBcIm5vZGVfbW9kdWxlcy9cIixcbiAgICAgICAgXCJlMmUvXCIsXG4gICAgICAgIFwic3JjL3Rlc3QvXCIsXG4gICAgICAgIFwic3JjL3R5cGVzL1wiLFxuICAgICAgICBcIioqL3R5cGVzLnRzXCIsXG4gICAgICAgIFwic3JjL21haW4udHN4XCIsXG4gICAgICAgIFwiKiovKi5kLnRzXCIsXG4gICAgICAgIFwiKiovKi5jb25maWcuKlwiLFxuICAgICAgICBcIioqL21vY2tEYXRhXCIsXG4gICAgICAgIFwiKiovKi50ZXN0Lnt0cyx0c3h9XCIsXG4gICAgICBdLFxuICAgICAgdGhyZXNob2xkczoge1xuICAgICAgICBzdGF0ZW1lbnRzOiA5NSxcbiAgICAgICAgYnJhbmNoZXM6IDk1LFxuICAgICAgICBmdW5jdGlvbnM6IDk1LFxuICAgICAgICBsaW5lczogOTUsXG4gICAgICB9LFxuICAgIH0sXG4gIH0sXG4gIHJlc29sdmU6IHtcbiAgICBhbGlhczoge1xuICAgICAgXCJAXCI6IHBhdGgucmVzb2x2ZShfX2Rpcm5hbWUsIFwiLi9zcmNcIiksXG4gICAgfSxcbiAgfSxcbn0pO1xuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUVBLFNBQVMsb0JBQW9CO0FBQzdCLE9BQU8sV0FBVztBQUNsQixPQUFPLFVBQVU7QUFKakIsSUFBTSxtQ0FBbUM7QUFNekMsSUFBTyx3QkFBUSxhQUFhO0FBQUEsRUFDMUIsU0FBUyxDQUFDLE1BQU0sQ0FBQztBQUFBLEVBQ2pCLEtBQUs7QUFBQSxJQUNILFNBQVM7QUFBQSxNQUNQLFNBQVMsQ0FBQztBQUFBLElBQ1o7QUFBQSxFQUNGO0FBQUEsRUFDQSxNQUFNO0FBQUEsSUFDSixTQUFTO0FBQUEsSUFDVCxhQUFhO0FBQUEsSUFDYixZQUFZO0FBQUEsSUFDWixLQUFLO0FBQUEsSUFDTCxhQUFhO0FBQUE7QUFBQTtBQUFBLElBR2IsU0FBUyxDQUFDLCtCQUErQjtBQUFBLElBQ3pDLFNBQVMsQ0FBQyxnQkFBZ0IsUUFBUSxPQUFPLHFCQUFxQixjQUFjO0FBQUEsSUFDNUUsV0FBVztBQUFBLE1BQ1QsU0FBUyxDQUFDLHdCQUF3QjtBQUFBLElBQ3BDO0FBQUEsSUFDQSxVQUFVO0FBQUEsTUFDUixVQUFVO0FBQUEsTUFDVixVQUFVLENBQUMsUUFBUSxRQUFRLE1BQU07QUFBQSxNQUNqQyxTQUFTO0FBQUEsUUFDUDtBQUFBLFFBQ0E7QUFBQSxRQUNBO0FBQUEsUUFDQTtBQUFBLFFBQ0E7QUFBQSxRQUNBO0FBQUEsUUFDQTtBQUFBLFFBQ0E7QUFBQSxRQUNBO0FBQUEsUUFDQTtBQUFBLE1BQ0Y7QUFBQSxNQUNBLFlBQVk7QUFBQSxRQUNWLFlBQVk7QUFBQSxRQUNaLFVBQVU7QUFBQSxRQUNWLFdBQVc7QUFBQSxRQUNYLE9BQU87QUFBQSxNQUNUO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFBQSxFQUNBLFNBQVM7QUFBQSxJQUNQLE9BQU87QUFBQSxNQUNMLEtBQUssS0FBSyxRQUFRLGtDQUFXLE9BQU87QUFBQSxJQUN0QztBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
