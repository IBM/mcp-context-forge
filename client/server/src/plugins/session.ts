// Location: ./client/server/src/plugins/session.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Decorates fastify with `sessionAuth`, a preHandler that resolves the
// session_id cookie against Redis and populates request.session. Applied
// per-route (proxy/auth/SSE), not globally — SSE routes need different CSRF
// treatment, and /healthz and /auth/login must stay unauthenticated.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import fp from "fastify-plugin";

import { getSession, SESSION_COOKIE_NAME } from "../lib/session-store.js";

async function sessionAuth(request: FastifyRequest, reply: FastifyReply): Promise<void> {
  const sessionId = request.cookies[SESSION_COOKIE_NAME];
  if (!sessionId) {
    reply.code(401).send({ error: "unauthenticated" });
    return;
  }

  const record = await getSession(request.server.redis, sessionId);

  if (!record) {
    reply.code(401).send({ error: "session_expired" });
    return;
  }

  request.session = { sessionId, bearerToken: record.bearerToken, user: record.user };
}

export default fp(
  async function sessionPlugin(fastify: FastifyInstance) {
    fastify.decorate("sessionAuth", sessionAuth);
  },
  { name: "sessionPlugin" },
);

declare module "fastify" {
  interface FastifyInstance {
    sessionAuth: typeof sessionAuth;
  }
}
