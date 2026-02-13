import { defineConfig } from "vitest/config";

export default defineConfig({
    test: {
        environment: "jsdom",
        globals: true,
        include: ["tests/js/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}"],
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
        coverage: {
            provider: "istanbul",
            reporter: ["text", "json", "html", "lcov"],
            include: ["mcpgateway/admin_ui/**/*.js", "mcpgateway/static/flame-graph.js", "mcpgateway/static/gantt-chart.js"],
            exclude: ["mcpgateway/static/bundle-*.js", "**/node_modules/**"],
        },
    },
});
