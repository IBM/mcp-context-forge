// Location: ./client/server/src/routes/app.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// The one route where the BFF decides server-side instead of leaving it to
// client-side routing: GET / redirects to the dashboard for an authenticated
// visitor, and to the login screen for everyone else, before any app JS
// loads. Both targets are under /app/ because the client router
// (client/src/router/index.tsx) hardcodes that prefix and only ever renders
// /app/* paths — a bare '/' matches none of its routes and would render a
// blank page if served directly instead of redirected. /app/* itself (and
// every other deep client route) falls through to plugins/static.ts's
// unconditional SPA-fallback 404 handler, where the client router's own
// AuthGuard takes over.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { getSession, SESSION_COOKIE_NAME } from "../lib/session-store.js";

const HOME_PATH = "/app/";
const LOGIN_PATH = "/app/login";

export default async function appRoute(fastify: FastifyInstance): Promise<void> {
  fastify.get("/", async (request: FastifyRequest, reply: FastifyReply) => {
    const sessionId = request.cookies[SESSION_COOKIE_NAME];
    const record = sessionId ? await getSession(fastify.redis, sessionId) : null;

    return reply.redirect(record ? HOME_PATH : LOGIN_PATH);
  });
}
