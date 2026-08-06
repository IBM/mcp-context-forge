// Location: ./client/server/src/index.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// BFF entrypoint. Plugin order matters: cookie -> redis -> session -> csrf,
// then routes. Session/CSRF are decorators applied per-route (see
// plugins/session.ts, plugins/csrf.ts), not global onRequest hooks, since
// SSE routes need different CSRF treatment than the /api/* catch-all.

import Fastify from "fastify";

import { config } from "./config.js";
import cookiePlugin from "./plugins/cookie.js";
import csrfPlugin from "./plugins/csrf.js";
import redisPlugin from "./plugins/redis.js";
import sessionPlugin from "./plugins/session.js";
import staticPlugin from "./plugins/static.js";
import appRoute from "./routes/app.js";
import loginRoute from "./routes/auth/login.js";
import logoutRoute from "./routes/auth/logout.js";
import sessionRoute from "./routes/auth/session.js";
import catchAllProxyRoute from "./routes/proxy/catch-all.js";
import { startRevocationSubscriber } from "./routes/sse/revocation-subscriber.js";
import sseRoutes from "./routes/sse/routes.js";

const fastify = Fastify({ logger: { level: config.logLevel } });

await fastify.register(cookiePlugin);
await fastify.register(redisPlugin);
await fastify.register(sessionPlugin);
await fastify.register(csrfPlugin);
await fastify.register(staticPlugin);

fastify.get("/healthz", async () => ({ ok: true }));

await fastify.register(loginRoute);
await fastify.register(logoutRoute);
await fastify.register(sessionRoute);
await fastify.register(sseRoutes);
await fastify.register(catchAllProxyRoute);
await fastify.register(appRoute);

const revocationSubscriber = startRevocationSubscriber();
fastify.addHook("onClose", async () => {
  await revocationSubscriber.quit();
});

try {
  await fastify.listen({ port: config.port, host: config.host });
} catch (err) {
  fastify.log.error(err);
  process.exit(1);
}
