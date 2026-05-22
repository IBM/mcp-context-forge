/**
 * Route paths used across the E2E suite.
 *
 * Mirrors the routes declared in `client/src/App.tsx` and the APP_PREFIX
 * constant in `client/src/router/index.tsx`. Keep in sync when routes change.
 */

export const APP = {
  ROOT: "/app/",
  LOGIN: "/app/login",
  FORGOT_PASSWORD: "/app/forgot-password",
  CHANGE_PASSWORD: "/app/change-password", // pragma: allowlist secret
  GATEWAYS: "/app/gateways",
  SERVERS: "/app/servers",
  TOOLS: "/app/tools",
  RESOURCES: "/app/resources",
  PROMPTS: "/app/prompts",
  AGENTS: "/app/agents",
  USERS: "/app/users",
  TEAMS: "/app/teams",
  TOKENS: "/app/tokens",
  METRICS: "/app/metrics",
  OBSERVABILITY: "/app/observability",
  PLUGINS: "/app/plugins",
  PERFORMANCE: "/app/performance",
  MAINTENANCE: "/app/maintenance",
  SETTINGS: "/app/settings",
  SERVER_CATALOG: "/app/server-catalog",
  LLM_PROVIDERS: "/app/llm/providers",
  LLM_MODELS: "/app/llm/models",
  NOT_FOUND: "/app/not-found",
} as const;

/**
 * API endpoints consumed by the client. Patterns use Playwright's glob syntax
 * so they match regardless of origin (dev vs. reverse-proxied gateway).
 */
export const API = {
  LOGIN: "**/app/auth/login",
  ME: "**/app/auth/me",
} as const;

/**
 * Legacy sessionStorage key kept so tests can assert cookie auth no longer writes it.
 */
export const TOKEN_STORAGE_KEY = "mcpgateway_token";
