import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
    plugins: [react()],
    test: {
        environment: "jsdom",
        globals: true,
        include: [
            "tests/js/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}",
            "client/**/*.test.js",
            "client/**/*.test.jsx",
        ],
        exclude: [
            "**/node_modules/**",
            "**/tests/playwright/**",
            "**/tests/unit/**",
            "**/tests/integration/**",
            "**/tests/e2e/**",
            "**/tests/performance/**",
            "**/tests/security/**",
            "**/tests/fuzz/**",
            "**/tests/load/**",
            "**/tests/loadtest/**",
            "**/tests/jmeter/**",
        ],
        setupFiles: ["client/setupTests.js"],
        coverage: {
            provider: "istanbul",
            reporter: ["text", "json", "html", "lcov"],
            include: ["mcpgateway/static/**/*.js"],
            exclude: ["mcpgateway/static/bundle.js", "**/node_modules/**"],
        },
    },
});
