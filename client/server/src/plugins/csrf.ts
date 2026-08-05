// Location: ./client/server/src/plugins/csrf.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Double-submit CSRF, browser<->BFF boundary only (BFF<->API is a
// server-to-server bearer token, no CSRF needed there). Cookie-mode
// (backed by @fastify/cookie, no server session store) since the BFF's own
// session plugin is hand-rolled, not @fastify/session.
//
// The cookie this plugin sets (bff_csrf) holds a *secret*, not the token —
// it stays HttpOnly. The actual token (`reply.generateCsrf()`'s return
// value) is handed to the SPA in the JSON body of /auth/login and
// /auth/session and must be echoed back in the X-CSRF-Token header on
// mutating requests. This differs from the pre-BFF pattern of reading the
// CSRF cookie straight off `document.cookie` (mcpgateway_csrf_token was the
// token itself, not a secret) — that pattern doesn't fit this library's
// secret/token split.
//
// Registered as a decorator (fastify.csrfProtection), applied per-route via
// preHandler — not globally — so SSE routes (which can't send custom
// headers) can opt out. See agent-output/bff-proxy-and-sse-plan.md Risk #2.

import fastifyCsrf from "@fastify/csrf-protection";
import type { FastifyInstance } from "fastify";
import fp from "fastify-plugin";

import { config } from "../config.js";

export const CSRF_COOKIE_NAME = "bff_csrf";

export default fp(
  async function csrfPlugin(fastify: FastifyInstance) {
    await fastify.register(fastifyCsrf, {
      cookieKey: CSRF_COOKIE_NAME,
      cookieOpts: {
        httpOnly: true,
        secure: config.cookieSecure,
        sameSite: "strict",
        path: "/",
        domain: config.cookieDomain,
      },
    });
  },
  { name: "csrfPlugin", dependencies: ["cookiePlugin"] },
);
