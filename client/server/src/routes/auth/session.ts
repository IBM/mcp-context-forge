// Location: ./client/server/src/routes/auth/session.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// GET /auth/session: SPA bootstrap probe. Never 401s past the network layer
// with a body the app can't use — returns { authenticated: false } for an
// anonymous visitor so the SPA can render a login screen without treating it
// as an error. Also (re)seeds the CSRF cookie, since a page reload needs one
// even mid-session.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { getSession, SESSION_COOKIE_NAME } from "../../lib/session-store.js";

export default async function sessionRoute(fastify: FastifyInstance): Promise<void> {
  fastify.get("/auth/session", async (request: FastifyRequest, reply: FastifyReply) => {
    const sessionId = request.cookies[SESSION_COOKIE_NAME];
    const record = sessionId ? await getSession(fastify.redis, sessionId) : null;

    if (!record) {
      return reply.send({ authenticated: false });
    }

    const csrfToken = await reply.generateCsrf();
    return reply.send({ authenticated: true, user: record.user, csrfToken });
  });
}
