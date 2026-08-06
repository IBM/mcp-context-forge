// Location: ./client/server/test/app.test.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// PUBLIC_DIR must be set before src/config.ts (and plugins/static.ts,
// transitively) is first evaluated — same env-ordering constraint as
// proxy.test.ts/sse.test.ts — so a temp SPA build dir is created and
// process.env.PUBLIC_DIR set in beforeAll, with modules under test
// dynamic-imported afterwards.

import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import Fastify, { type FastifyInstance } from "fastify";
import type { Redis } from "ioredis";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

let publicDir: string;

beforeAll(async () => {
  publicDir = await mkdtemp(path.join(tmpdir(), "bff-public-"));
  await writeFile(
    path.join(publicDir, "index.html"),
    "<!doctype html><title>spa-shell-marker</title>",
  );
  process.env.PUBLIC_DIR = publicDir;
});

afterAll(() => rm(publicDir, { recursive: true, force: true }));

async function buildApp(): Promise<{
  fastify: FastifyInstance;
  redis: import("./helpers/build-app.js").FakeRedis;
}> {
  const { FakeRedis } = await import("./helpers/build-app.js");
  const cookiePlugin = (await import("../src/plugins/cookie.js")).default;
  const sessionPlugin = (await import("../src/plugins/session.js")).default;
  const staticPlugin = (await import("../src/plugins/static.js")).default;
  const appRoute = (await import("../src/routes/app.js")).default;
  const catchAllProxyRoute = (await import("../src/routes/proxy/catch-all.js")).default;

  const fastify = Fastify();
  const redis = new FakeRedis();
  fastify.decorate("redis", redis as unknown as Redis);
  await fastify.register(cookiePlugin);
  await fastify.register(sessionPlugin);
  await fastify.register(staticPlugin);
  await fastify.register(catchAllProxyRoute); // registered alongside app/static to prove /api/* isn't swallowed by the SPA fallback
  await fastify.register(appRoute);

  return { fastify, redis };
}

let app: Awaited<ReturnType<typeof buildApp>>;

afterEach(async () => {
  await app?.fastify.close();
});

describe("GET /", () => {
  it("redirects an anonymous visitor to /app/login", async () => {
    app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/" });

    expect(response.statusCode).toBe(302);
    expect(response.headers.location).toBe("/app/login");
  });

  it("redirects an authenticated visitor to /app/", async () => {
    app = await buildApp();
    const { createSession } = await import("../src/lib/session-store.js");
    const sessionId = await createSession(app.redis as never, {
      bearerToken: "test-bearer-token", // pragma: allowlist secret
      user: { email: "user@example.com", isAdmin: false },
    });

    const response = await app.fastify.inject({
      method: "GET",
      url: "/",
      headers: { cookie: `bff_sid=${sessionId}` },
    });

    expect(response.statusCode).toBe(302);
    expect(response.headers.location).toBe("/app/");
  });
});

describe("SPA fallback (404 handler)", () => {
  it("serves the app shell for /app/login (the client router's own auth screen)", async () => {
    app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/app/login" });

    expect(response.statusCode).toBe(200);
    expect(response.body).toContain("spa-shell-marker");
  });

  it("serves the app shell for a deep client-side route", async () => {
    app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/app/tools" });

    expect(response.statusCode).toBe(200);
    expect(response.body).toContain("spa-shell-marker");
  });

  it("404s a missing asset instead of serving the app shell", async () => {
    app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/assets/does-not-exist.js" });

    expect(response.statusCode).toBe(404);
    expect(response.body).not.toContain("spa-shell-marker");
  });

  it("does not swallow /api/* into the SPA fallback", async () => {
    app = await buildApp();
    const response = await app.fastify.inject({ method: "GET", url: "/api/tools" });

    // 401 (no session) proves the catch-all's own auth check ran, not the fallback.
    expect(response.statusCode).toBe(401);
    expect(response.body).not.toContain("spa-shell-marker");
  });
});
