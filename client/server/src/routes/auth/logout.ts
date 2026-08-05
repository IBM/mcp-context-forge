// Location: ./client/server/src/routes/auth/logout.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// POST /auth/logout: CSRF-protected like any other state-changing
// browser->BFF call. Idempotent w.r.t. session state — clears cookies and
// drops the Redis session even if session_id is already missing/expired
// (double-click or retry), as long as the caller still holds a valid CSRF
// cookie/token pair.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { clearSessionCookie, deleteSession, SESSION_COOKIE_NAME } from "../../lib/session-store.js";
import { CSRF_COOKIE_NAME } from "../../plugins/csrf.js";

export default async function logoutRoute(fastify: FastifyInstance): Promise<void> {
  fastify.post(
    "/auth/logout",
    { preHandler: [fastify.csrfProtection] },
    async (request: FastifyRequest, reply: FastifyReply) => {
      const sessionId = request.cookies[SESSION_COOKIE_NAME];
      if (sessionId) {
        await deleteSession(fastify.redis, sessionId);
      }

      clearSessionCookie(reply);
      reply.clearCookie(CSRF_COOKIE_NAME, { path: "/" });

      return reply.send({ ok: true });
    },
  );
}
