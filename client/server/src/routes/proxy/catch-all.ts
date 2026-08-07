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
import { clearSessionCookie, deleteSession } from "../../lib/session-store.js";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

// FastAPI/Starlette 307s bare "/teams" -> "/teams/" (redirect_slashes) with an
// absolute Location built from its own host:port. Passed through unmodified,
// the browser would follow it straight to FastAPI — leaking the upstream
// origin and losing the BFF session (FastAPI has no bearer token or
// understanding of the bff_sid cookie). Rewrite it back to a same-origin
// /api/* path so every hop stays behind the BFF.
function rewriteUpstreamLocation(
  headers: Record<string, string | string[] | undefined>,
): typeof headers {
  const location = headers.location;
  if (typeof location !== "string" || !location.startsWith(config.fastapiUrl)) {
    return headers;
  }
  const upstreamPath = location.slice(config.fastapiUrl.length);
  return { ...headers, location: `/api${upstreamPath}` };
}

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

  // Fastify's default JSON parser throws FST_ERR_CTP_EMPTY_JSON_BODY on an
  // empty body with Content-Type: application/json — before preHandler, so
  // before this route (or even sessionAuth) ever runs. Several real calls
  // (e.g. the tool/gateway activate-state toggle) send that header with no
  // body at all.
  //
  // This must still produce a real parsed object for a non-empty body, not
  // a raw Buffer passthrough: @fastify/reply-from unconditionally
  // JSON.stringify()s request.body whenever Content-Type is
  // application/json (contentTypesToEncode always includes it, with no way
  // to opt out — see its index.js). A raw Buffer JSON.stringifies to
  // `{"type":"Buffer","data":[...]}`, corrupting every JSON body sent
  // through the proxy. So: parse for real (letting reply-from's re-encode
  // round-trip correctly), just don't throw on empty.
  fastify.addContentTypeParser("application/json", { parseAs: "string" }, (_req, rawBody, done) => {
    const body = rawBody.toString();
    if (!body) {
      done(null, undefined);
      return;
    }
    try {
      done(null, JSON.parse(body));
    } catch (err) {
      done(err as Error, undefined);
    }
  });

  fastify.all(
    "/api/*",
    { preHandler: [fastify.sessionAuth, csrfIfUnsafe] },
    async (request: FastifyRequest, reply: FastifyReply) => {
      // Wildcard capture excludes the leading '/api/'; FastAPI routes are
      // mounted at root, so reattach a single leading slash.
      const wildcard = (request.params as Record<string, string>)["*"] ?? "";
      const upstreamPath = `/${wildcard}`;
      const bearerToken = request.session!.bearerToken;

      const sessionId = request.session!.sessionId;

      return reply.from(upstreamPath, {
        rewriteRequestHeaders: (_req, headers) => ({
          ...headers,
          authorization: `Bearer ${bearerToken}`,
        }),
        rewriteHeaders: rewriteUpstreamLocation,
        onResponse: (req, res, upstreamResponse) => {
          // 401 from upstream means the bearer token itself is dead
          // (expired/invalid) — not a permissions problem (that's 403,
          // left alone; a valid session can still get 403s). Drop the BFF
          // session and clear cookies now rather than let the browser keep
          // retrying with a token that will never become valid again;
          // its next call 401s from sessionAuth and the SPA's existing
          // redirect-to-login handles the rest.
          if (upstreamResponse.statusCode === 401) {
            deleteSession(fastify.redis, sessionId).catch((err) =>
              req.log.warn({ err, sessionId }, "failed to revoke session after upstream 401"),
            );
            // reply-from's onResponse types `res` generically enough (HTTP/2 union)
            // to not structurally match FastifyReply; this app never runs HTTP/2.
            clearSessionCookie(res as unknown as FastifyReply);
          }
          res.send(upstreamResponse.stream);
        },
      });
    },
  );
}
