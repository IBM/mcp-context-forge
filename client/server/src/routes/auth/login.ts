// Location: ./client/server/src/routes/auth/login.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// POST /auth/login: browser -> BFF only. The BFF makes its own
// server-to-server call to the upstream FastAPI login endpoint and never
// forwards the resulting access_token to the browser — only an opaque
// session_id cookie goes back. See agent-output/microfrontend-bff-auth-architecture.md.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { config } from "../../config.js";
import { createSession, setSessionCookie, type SessionUser } from "../../lib/session-store.js";

interface LoginBody {
  email: string;
  password: string;
}

// Mirrors mcpgateway.schemas.AuthenticationResponse. `user` is forwarded to
// the browser verbatim (see SessionUser) — the BFF only needs access_token
// and expires_in.
interface UpstreamAuthenticationResponse {
  access_token: string;
  expires_in: number;
  user: SessionUser;
}

export default async function loginRoute(fastify: FastifyInstance): Promise<void> {
  fastify.post<{ Body: LoginBody }>(
    "/auth/login",
    async (request: FastifyRequest<{ Body: LoginBody }>, reply: FastifyReply) => {
      const { email, password } = request.body ?? {};
      if (!email || !password) {
        return reply.code(400).send({ error: "email and password are required" });
      }

      const upstreamResponse = await fetch(`${config.fastapiUrl}/auth/email/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!upstreamResponse.ok) {
        // Upstream 401/403/429 pass through as-is; body may carry rate-limit or
        // lockout detail the SPA's login form wants to show.
        const detail = await upstreamResponse.text();
        return reply.code(upstreamResponse.status).send({ error: "login_failed", detail });
      }

      const auth = (await upstreamResponse.json()) as UpstreamAuthenticationResponse; // pragma: allowlist secret

      // The BFF session/cookie must not outlive the bearer token it wraps —
      // use the upstream JWT's own lifetime, not a fixed BFF-side default.
      // See createSession's comment in lib/session-store.ts.
      const ttlSeconds =
        Number.isFinite(auth.expires_in) && auth.expires_in > 0
          ? auth.expires_in
          : config.sessionTtlSeconds;

      const sessionId = await createSession(
        fastify.redis,
        {
          bearerToken: auth.access_token,
          user: auth.user,
        },
        ttlSeconds,
      );

      setSessionCookie(reply, sessionId, ttlSeconds);
      // Cookie holds the CSRF secret (HttpOnly); the SPA needs the derived
      // token itself to echo back via X-CSRF-Token — see plugins/csrf.ts.
      const csrfToken = await reply.generateCsrf();

      return reply.send({ user: auth.user, csrfToken });
    },
  );
}
