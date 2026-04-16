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
  CHANGE_PASSWORD: "/app/change-password",
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
  LOGIN: "**/auth/login",
  ME: "**/auth/me",
} as const;

/**
 * sessionStorage key the client uses for the bearer token. Must match
 * `TOKEN_KEY` in `client/src/api/client.ts`.
 */
export const TOKEN_STORAGE_KEY = "mcpgateway_token";
