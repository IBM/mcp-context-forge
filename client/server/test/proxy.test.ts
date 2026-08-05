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
let lastRequest: { path: string; authorization: string | undefined; method: string } | undefined;

beforeAll(async () => {
  upstream = createServer((req: IncomingMessage, res) => {
    lastRequest = {
      path: req.url ?? "",
      authorization: req.headers.authorization,
      method: req.method ?? "",
    };
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
  });
  await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", () => resolve()));
  const { port } = upstream.address() as AddressInfo;
  process.env.FASTAPI_URL = `http://127.0.0.1:${port}`;
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

  it("forwards a state-changing request given a valid CSRF token", async () => {
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
  });
});
