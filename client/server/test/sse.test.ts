// Location: ./client/server/test/sse.test.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Exercises the real network path (fastify.listen + fetch), not
// fastify.inject(), because reply.hijack() takes the response out of
// Fastify/light-my-request's normal capture path — inject() would hang
// waiting for a stream that's designed to live indefinitely.
//
// Same env-ordering constraint as proxy.test.ts: FASTAPI_URL must be set
// before anything importing src/config.ts (transitively, the SSE upstream
// pool) is first evaluated, so every module under test is dynamic-imported
// after the fake upstream server is listening.

import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import Fastify, { type FastifyInstance } from "fastify";
import type { Redis } from "ioredis";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

let upstream: Server;
let upstreamSocketCount = 0;

beforeAll(async () => {
  upstream = createServer((req, res) => {
    if (req.url === "/roots/changes") {
      upstreamSocketCount += 1;
      res.on("close", () => {
        upstreamSocketCount -= 1;
      });
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.write("data: hello\n\n");
      // Deliberately never ends — mirrors FastAPI's indefinite SSE stream.
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, path: req.url }));
  });
  await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", () => resolve()));
  const { port } = upstream.address() as AddressInfo;
  process.env.FASTAPI_URL = `http://127.0.0.1:${port}`;
  process.env.SSE_SESSION_RECHECK_SECONDS = "3600"; // keep the recheck timer out of the way of these tests
});

afterAll(() => new Promise<void>((resolve) => upstream.close(() => resolve())));

interface App {
  fastify: FastifyInstance;
  redis: import("./helpers/build-app.js").FakeRedis;
  baseUrl: string;
}

async function buildRunningApp(): Promise<App> {
  const { FakeRedis } = await import("./helpers/build-app.js");
  const cookiePlugin = (await import("../src/plugins/cookie.js")).default;
  const sessionPlugin = (await import("../src/plugins/session.js")).default;
  const sseRoutes = (await import("../src/routes/sse/routes.js")).default;
  const catchAllProxyRoute = (await import("../src/routes/proxy/catch-all.js")).default;

  const fastify = Fastify();
  const redis = new FakeRedis();
  fastify.decorate("redis", redis as unknown as Redis);
  await fastify.register(cookiePlugin);
  await fastify.register(sessionPlugin);
  await fastify.register(sseRoutes);
  await fastify.register(catchAllProxyRoute); // registered alongside SSE routes to prove routing precedence

  await fastify.listen({ port: 0, host: "127.0.0.1" });
  const address = fastify.server.address() as AddressInfo;
  return { fastify, redis, baseUrl: `http://127.0.0.1:${address.port}` };
}

async function seedSessionCookie(app: App): Promise<string> {
  const { createSession } = await import("../src/lib/session-store.js");
  const sessionId = await createSession(app.redis as never, {
    bearerToken: "test-bearer-token", // pragma: allowlist secret
    user: { email: "user@example.com", isAdmin: false },
  });
  return `bff_sid=${sessionId}`;
}

describe("SSE proxy", () => {
  it("routes /api/roots/changes to the SSE handler, not the /api/* catch-all", async () => {
    const app = await buildRunningApp();
    try {
      const cookie = await seedSessionCookie(app);
      const response = await fetch(`${app.baseUrl}/api/roots/changes`, { headers: { cookie } });
      expect(response.headers.get("content-type")).toContain("text/event-stream");
      await response.body?.cancel();
    } finally {
      await app.fastify.close();
    }
  });

  it("streams upstream events through to the client", async () => {
    const app = await buildRunningApp();
    try {
      const cookie = await seedSessionCookie(app);
      const response = await fetch(`${app.baseUrl}/api/roots/changes`, { headers: { cookie } });
      const reader = response.body!.getReader();
      const { value } = await reader.read();
      expect(new TextDecoder().decode(value)).toContain("data: hello");
      await reader.cancel();
    } finally {
      await app.fastify.close();
    }
  });

  it("aborts the upstream socket when the client disconnects", async () => {
    const app = await buildRunningApp();
    try {
      const cookie = await seedSessionCookie(app);
      const controller = new AbortController();
      const response = await fetch(`${app.baseUrl}/api/roots/changes`, {
        headers: { cookie },
        signal: controller.signal,
      });
      const reader = response.body!.getReader();
      await reader.read(); // make sure the stream is actually flowing first
      expect(upstreamSocketCount).toBe(1);

      controller.abort();
      await new Promise((resolve) => setTimeout(resolve, 100)); // let close events propagate

      expect(upstreamSocketCount).toBe(0);
    } finally {
      await app.fastify.close();
    }
  });
});
