// Location: ./client/server/test/proxy.test.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// FASTAPI_URL must be set before src/config.ts (and anything importing it)
// is first evaluated, so the fake upstream server is spun up and
// process.env.FASTAPI_URL set in beforeAll, with every module under test
// dynamic-imported afterwards rather than statically at the top of the file.

import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

let upstream: Server;
let upstreamOrigin: string;
let lastRequest:
  | { path: string; authorization: string | undefined; method: string; body: string }
  | undefined;

beforeAll(async () => {
  upstream = createServer((req: IncomingMessage, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      lastRequest = {
        path: req.url ?? "",
        authorization: req.headers.authorization,
        method: req.method ?? "",
        body: Buffer.concat(chunks).toString("utf8"),
      };
      // Mirrors Starlette's redirect_slashes: bare "/teams" -> "/teams/"
      // with an absolute Location built from the upstream's own host:port.
      if (req.url === "/teams") {
        res.writeHead(307, { location: `${upstreamOrigin}/teams/` });
        res.end();
        return;
      }
      // Simulates an expired/invalid bearer token — FastAPI's real
      // rbac middleware rejects with 401 here.
      if (req.url === "/expired") {
        res.writeHead(401, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "Token has expired" }));
        return;
      }
      // Simulates a valid session with insufficient RBAC permissions —
      // must not be treated the same as an expired token.
      if (req.url === "/forbidden") {
        res.writeHead(403, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "Insufficient permissions" }));
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", () => resolve()));
  const { port } = upstream.address() as AddressInfo;
  upstreamOrigin = `http://127.0.0.1:${port}`;
  process.env.FASTAPI_URL = upstreamOrigin;
});

afterAll(() => new Promise<void>((resolve) => upstream.close(() => resolve())));

async function buildApp() {
  const { buildTestApp } = await import("./helpers/build-app.js");
  return buildTestApp({ withProxy: true });
}

async function seedSession(app: Awaited<ReturnType<typeof buildApp>>) {
  const { createSession } = await import("../src/lib/session-store.js");
  const sessionId = await createSession(app.redis as never, {
    bearerToken: "test-bearer-token", // pragma: allowlist secret
    user: { email: "user@example.com", isAdmin: false },
  });

  // Round-trip through /auth/session to get a real CSRF cookie + token pair
  // tied to this Fastify instance, the same way the SPA would.
  const sessionProbe = await app.fastify.inject({
    method: "GET",
    url: "/auth/session",
    headers: { cookie: `bff_sid=${sessionId}` },
  });
  const csrfCookie = sessionProbe.cookies.find((c) => c.name === "bff_csrf");
  const csrfToken = sessionProbe.json().csrfToken as string;

  return {
    cookie: `bff_sid=${sessionId}; bff_csrf=${csrfCookie?.value}`,
    csrfToken,
  };
}

describe("ALL /api/*", () => {
  it("401s without a session cookie", async () => {
    const app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/api/tools" });
    expect(response.statusCode).toBe(401);
  });

  it("strips the /api prefix and injects Authorization for an authenticated GET", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "GET",
      url: "/api/tools?limit=5",
      headers: { cookie },
    });

    expect(response.statusCode).toBe(200);
    expect(lastRequest?.path).toBe("/tools?limit=5");
    expect(lastRequest?.authorization).toBe("Bearer test-bearer-token");
  });

  it("never lets the browser override the injected Authorization header", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    await app.fastify.inject({
      method: "GET",
      url: "/api/tools",
      headers: { cookie, authorization: "Bearer attacker-supplied-token" }, // pragma: allowlist secret
    });

    expect(lastRequest?.authorization).toBe("Bearer test-bearer-token");
  });

  it("rejects a state-changing request without a CSRF token", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/api/tools",
      headers: { cookie },
      payload: { name: "x" },
    });

    expect(response.statusCode).toBe(403);
  });

  it("forwards a state-changing request given a valid CSRF token, with the JSON body intact", async () => {
    const app = await buildApp();
    const { cookie, csrfToken } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/api/tools",
      headers: { cookie, "x-csrf-token": csrfToken },
      payload: { name: "x" },
    });

    expect(response.statusCode).toBe(200);
    expect(lastRequest?.method).toBe("POST");
    // @fastify/reply-from always JSON.stringify()s request.body for
    // Content-Type: application/json (no way to opt out — see catch-all.ts).
    // A naive raw-Buffer passthrough JSON.stringifies to
    // {"type":"Buffer","data":[...]}; must round-trip as real JSON instead.
    expect(JSON.parse(lastRequest!.body)).toEqual({ name: "x" });
  });

  it("forwards a state-changing request with Content-Type: application/json but no body (e.g. an activate/deactivate toggle)", async () => {
    const app = await buildApp();
    const { cookie, csrfToken } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/api/gateways/gw-1/state?activate=false",
      headers: { cookie, "x-csrf-token": csrfToken, "content-type": "application/json" },
    });

    // Fastify's default JSON parser 400s an empty body under this
    // Content-Type before the request ever reaches this route — must not
    // regress to that (see catch-all.ts's addContentTypeParser override).
    expect(response.statusCode).toBe(200);
    expect(lastRequest?.method).toBe("POST");
    expect(lastRequest?.body).toBe("");
  });

  it("rewrites an upstream redirect's absolute Location back to a same-origin /api/* path", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "GET",
      url: "/api/teams",
      headers: { cookie },
    });

    expect(response.statusCode).toBe(307);
    // Must never leak the upstream host:port to the browser, or the
    // redirect would leave the BFF and drop the session entirely.
    expect(response.headers.location).toBe("/api/teams/");
  });

  it("revokes the BFF session when upstream returns 401 (expired/invalid bearer token)", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "GET",
      url: "/api/expired",
      headers: { cookie },
    });

    expect(response.statusCode).toBe(401);
    const clearedCookie = response.cookies.find((c) => c.name === "bff_sid");
    expect(clearedCookie?.value).toBe("");

    // Not just the cookie cleared client-side — the session is really gone,
    // so a follow-up request can't keep retrying with a dead token.
    const followUp = await app.fastify.inject({
      method: "GET",
      url: "/auth/session",
      headers: { cookie },
    });
    expect(followUp.json()).toEqual({ authenticated: false });
  });

  it("does not revoke the session on a plain 403 (valid session, insufficient permissions)", async () => {
    const app = await buildApp();
    const { cookie } = await seedSession(app);

    const response = await app.fastify.inject({
      method: "GET",
      url: "/api/forbidden",
      headers: { cookie },
    });
    expect(response.statusCode).toBe(403);

    const followUp = await app.fastify.inject({
      method: "GET",
      url: "/auth/session",
      headers: { cookie },
    });
    expect(followUp.json().authenticated).toBe(true);
  });
});
