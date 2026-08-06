// Location: ./client/server/src/config.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Env-driven config for the BFF. All values have dev-safe defaults; override
// via env in every non-local deployment (COOKIE_SECURE and FASTAPI_URL in
// particular).

function optional(name: string, fallback: string): string {
  return process.env[name] ?? fallback;
}

export const config = {
  port: Number(optional("PORT", "3000")),
  host: optional("HOST", "0.0.0.0"),

  // Upstream ContextForge API (FastAPI). All bearer-token traffic goes here,
  // server-to-server only — the browser never talks to this origin directly.
  fastapiUrl: optional("FASTAPI_URL", "http://127.0.0.1:4444"),

  // memory:// (default) = in-process store, no Redis needed — dev only.
  // See lib/memory-redis.ts. Use a real redis:// URL beyond a single
  // local dev process.
  redisUrl: optional("REDIS_URL", "memory://"),

  // Opaque session_id -> { bearerToken, user } TTL in Redis. Independent of
  // the upstream JWT's own expiry; the BFF just stops trusting a stale
  // session key once this elapses.
  sessionTtlSeconds: Number(optional("SESSION_TTL_SECONDS", "86400")),

  cookieDomain: process.env.COOKIE_DOMAIN, // undefined = host-only cookie
  cookieSecure: optional("COOKIE_SECURE", "true") === "true",

  // SPA build directory (see plugins/static.ts). undefined = default,
  // computed relative to that plugin's own file location
  // (`cd client && npm run build:bff` -> client/server/public/). Override
  // for a non-standard layout, or to point at a temp dir in tests.
  publicDir: process.env.PUBLIC_DIR,

  // Session-revocation re-check cadence for long-lived SSE connections
  // (Option A from agent-output/bff-proxy-and-sse-plan.md — bounded staleness,
  // no pub/sub required). Revisit if instant revocation becomes a hard requirement.
  sseSessionRecheckSeconds: Number(optional("SSE_SESSION_RECHECK_SECONDS", "15")),

  logLevel: optional("LOG_LEVEL", "info"),
} as const;

if (process.env.NODE_ENV === "production" && config.redisUrl.startsWith("memory://")) {
  throw new Error("REDIS_URL=memory:// is dev-only — set a real redis:// URL in production");
}
