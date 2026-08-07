// Location: ./client/server/test/helpers/build-app.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Test fixture: a Fastify instance wired the same way as src/index.ts, but
// with an in-memory fake in place of plugins/redis.ts so tests don't need a
// real Redis instance. Only the ioredis surface the app actually touches
// (get/setex/del/publish) is implemented.

import Fastify, { type FastifyInstance } from "fastify";
import { type Redis } from "ioredis";

import cookiePlugin from "../../src/plugins/cookie.js";
import csrfPlugin from "../../src/plugins/csrf.js";
import sessionPlugin from "../../src/plugins/session.js";
import loginRoute from "../../src/routes/auth/login.js";
import logoutRoute from "../../src/routes/auth/logout.js";
import sessionRoute from "../../src/routes/auth/session.js";
import catchAllProxyRoute from "../../src/routes/proxy/catch-all.js";

export class FakeRedis {
  private store = new Map<string, string>();
  public published: Array<{ channel: string; message: string }> = [];

  async get(key: string): Promise<string | null> {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  async setex(key: string, _ttlSeconds: number, value: string): Promise<"OK"> {
    this.store.set(key, value);
    return "OK";
  }

  async del(key: string): Promise<number> {
    return this.store.delete(key) ? 1 : 0;
  }

  async publish(channel: string, message: string): Promise<number> {
    this.published.push({ channel, message });
    return 0;
  }
}

export interface TestApp {
  fastify: FastifyInstance;
  redis: FakeRedis;
}

export async function buildTestApp(opts: { withProxy?: boolean } = {}): Promise<TestApp> {
  const fastify = Fastify();
  const redis = new FakeRedis();
  fastify.decorate("redis", redis as unknown as Redis);

  await fastify.register(cookiePlugin);
  await fastify.register(sessionPlugin);
  await fastify.register(csrfPlugin);

  await fastify.register(loginRoute);
  await fastify.register(logoutRoute);
  await fastify.register(sessionRoute);

  if (opts.withProxy) {
    await fastify.register(catchAllProxyRoute);
  }

  await fastify.ready();
  return { fastify, redis };
}

/** Parse `Set-Cookie` response headers into a `name=value; name2=value2` request Cookie header. */
export function cookieHeaderFrom(setCookieHeaders: string[] | undefined): string {
  return (setCookieHeaders ?? []).map((raw) => raw.split(";")[0]).join("; ");
}
