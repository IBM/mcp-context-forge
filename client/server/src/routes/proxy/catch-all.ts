// Location: ./client/server/src/routes/proxy/catch-all.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Generic `/api/*` -> FastAPI proxy. Covers the bulk of the API surface
// without mirroring routes: session lookup -> inject Authorization header ->
// forward via @fastify/reply-from. Only BFF-owned auth routes and SSE routes
// (registered separately, see routes/sse/) are excluded — find-my-way
// resolves their static paths before this wildcard regardless of
// registration order, so there's no risk of this route swallowing them.
//
// SAFE_METHODS mirrors mcpgateway/middleware/csrf_middleware.py so the
// browser<->BFF CSRF boundary matches the same-origin behavior it replaces.

import replyFrom from "@fastify/reply-from";
import type {
  FastifyInstance,
  FastifyReply,
  FastifyRequest,
  HookHandlerDoneFunction,
} from "fastify";

import { config } from "../../config.js";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

// fastify.csrfProtection is callback-style (request, reply, done), not
// promise-returning — mirror that shape rather than mixing async/await with it.
function csrfIfUnsafe(
  request: FastifyRequest,
  reply: FastifyReply,
  done: HookHandlerDoneFunction,
): void {
  if (SAFE_METHODS.has(request.method)) return done();
  request.server.csrfProtection(request, reply, done);
}

export default async function catchAllProxyRoute(fastify: FastifyInstance): Promise<void> {
  await fastify.register(replyFrom, { base: config.fastapiUrl });

  fastify.all(
    "/api/*",
    { preHandler: [fastify.sessionAuth, csrfIfUnsafe] },
    async (request: FastifyRequest, reply: FastifyReply) => {
      // Wildcard capture excludes the leading '/api/'; FastAPI routes are
      // mounted at root, so reattach a single leading slash.
      const wildcard = (request.params as Record<string, string>)["*"] ?? "";
      const upstreamPath = `/${wildcard}`;
      const bearerToken = request.session!.bearerToken;

      return reply.from(upstreamPath, {
        rewriteRequestHeaders: (_req, headers) => ({
          ...headers,
          authorization: `Bearer ${bearerToken}`,
        }),
      });
    },
  );
}
